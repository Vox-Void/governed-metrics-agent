import json
import subprocess
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from governed_metrics.auth import PROFILES
from governed_metrics.compiler import Statement, compile_metric
from governed_metrics.executor import DuckDBExecutor, QueryFailure
from governed_metrics.planner import Proposal, ScriptedPlanner, date_window
from governed_metrics.schemas import Answer, MetricPlan, Watermark
from governed_metrics.service import Service, display
from governed_metrics.snapshots import ROOT, pin_snapshot
from governed_metrics.worker import execute

GOLDENS = json.loads((ROOT / "data/goldens.json").read_bytes())
SCOPE = "in ZAR on 1-2 November 2026"


def ask(service, metric, scope=SCOPE, *, merchant="a", profile="analyst-a", variant="fresh"):
    return service.ask(
        f"{metric} {scope}", merchant, PROFILES[profile], ScriptedPlanner(), variant=variant
    )


def plan(**fields):
    return json.dumps(
        {
            "kind": "plan",
            "merchant": "a",
            "currency": "ZAR",
            "grouping": "total",
            "metric_id": "net_collected",
            "start": "2026-11-01",
            "end": "2026-11-03",
            "provider": None,
            **fields,
        }
    )


class NoQuery:
    def query(self, path, statement):
        pytest.fail("This request must stop before a fact query.")


class RoguePlanner:
    mode = "test"

    def __init__(self, payload):
        self.payload = payload

    def propose(self, question, context):
        return Proposal(self.payload)


@pytest.mark.parametrize(
    "fixture,scope",
    [
        ("a_zar_total", SCOPE),
        ("a_zar_card", SCOPE + " CARD"),
        ("a_usd_total", "in USD on 1-2 November 2026"),
        ("a_zar_empty", "in ZAR yesterday"),
    ],
)
def test_golden_total_rows(snapshot_root, fixture, scope):
    service = Service(snapshot_root)
    for metric, expected in GOLDENS[fixture].items():
        outcome = ask(service, metric, scope)
        assert isinstance(outcome, Answer), outcome
        row = outcome.rows[0]
        if metric == "payment_success_rate":
            assert [row.value, row.numerator, row.denominator] == expected
        else:
            assert row.value == expected
        assert outcome.query_hash and outcome.snapshot_id


def test_merchant_partition_and_order_grain(snapshot_root):
    service = Service(snapshot_root)
    separate = ask(service, "net collected", merchant="b", profile="analyst-b")
    assert separate.rows[0].value == GOLDENS["b_zar_total"]["net_collected"]
    total = ask(service, "paying orders")
    daily = ask(service, "paying orders by day")
    assert total.rows[0].value == 2
    assert [(row.group, row.value) for row in daily.rows] == [("2026-11-01", 1), ("2026-11-02", 2)]


def test_refunds_for_an_old_capture_and_split_provider_groups(snapshot_root):
    service = Service(snapshot_root)
    by_provider = ask(service, "net collected by provider")
    assert {row.group: row.value for row in by_provider.rows} == GOLDENS["a_zar_net_by_provider"]
    negative = ask(service, "net collected", "CARD ZAR on 2 November")
    assert negative.rows[0].value == -2000
    assert "ZAR -20.00" in display(negative)
    empty_eft = ask(service, "captured amount by provider", "USD on 1-2 November")
    assert [(row.group, row.value) for row in empty_eft.rows] == [("CARD", 700), ("EFT", 0)]


def test_ambiguous_stale_and_denied_requests_never_query(snapshot_root):
    service = Service(snapshot_root, executor=NoQuery())
    assert ask(service, "revenue").reason == "AMBIGUOUS_METRIC"
    assert ask(service, "net collected", variant="stale-refunds").reason == "STALE_INPUT"
    unknown = ask(service, "net collected", merchant="unknown")
    known = ask(service, "net collected", merchant="b")
    assert unknown.model_dump(exclude={"trace_id"}) == known.model_dump(exclude={"trace_id"})


def test_out_of_scope_request_stops_before_planner(snapshot_root):
    class NeverCalled:
        mode = "test"

        def propose(self, question, context):
            pytest.fail("Authorize the merchant before calling the planner.")

    service = Service(snapshot_root, executor=NoQuery())
    response = service.ask("Show anything", "b", PROFILES["analyst-a"], NeverCalled())
    assert response.reason == "SCOPE_DENIED"
    assert service.discover("b", PROFILES["analyst-a"])["reason"] == "SCOPE_DENIED"


@pytest.mark.parametrize(
    "override,reason",
    [
        ({"merchant": "b"}, "SCOPE_DENIED"),
        ({"sql": "SELECT 1"}, "INVALID_PLAN"),
        ({"metric_id": "unregistered"}, "INVALID_PLAN"),
        ({"start": "2026-02-31"}, "INVALID_PLAN"),
        ({"start": "2026-11-03"}, "DATE_REQUIRED"),
        ({"start": "2026-09-01"}, "WINDOW_TOO_LONG"),
    ],
)
def test_planner_output_cannot_expand_authority(snapshot_root, override, reason):
    service = Service(snapshot_root, executor=NoQuery())
    outcome = service.ask("Test", "a", PROFILES["analyst-a"], RoguePlanner(plan(**override)))
    assert outcome.reason == reason
    assert "rows" not in outcome.model_dump()


def test_ops_profile_has_only_card_rate_permission(snapshot_root):
    service = Service(snapshot_root, executor=NoQuery())
    profile = PROFILES["ops-a"]
    assert list(service.discover("a", profile)["metrics"]) == ["payment_success_rate"]
    assert service.structured(plan(), "a", profile).reason == "SCOPE_DENIED"
    assert (
        service.structured(
            plan(metric_id="payment_success_rate", provider="EFT"), "a", profile
        ).reason
        == "SCOPE_DENIED"
    )
    assert (
        service.structured(plan(metric_id="payment_success_rate"), "a", profile).reason
        == "CONFIRM_PROVIDER"
    )


def test_planner_cannot_guess_scope_the_reader_did_not_request(snapshot_root):
    service = Service(snapshot_root, executor=NoQuery())
    ops = RoguePlanner(plan(provider="CARD", metric_id="payment_success_rate"))
    assert (
        service.ask(f"Payment success rate {SCOPE}", "a", PROFILES["ops-a"], ops).reason
        == "CONFIRM_PROVIDER"
    )
    analyst = RoguePlanner(plan())
    assert (
        service.ask("Net collected on 1-2 November", "a", PROFILES["analyst-a"], analyst).reason
        == "CURRENCY_REQUIRED"
    )
    assert (
        service.ask("Net collected in ZAR yesterday", "a", PROFILES["analyst-a"], analyst).reason
        == "DATE_REQUIRED"
    )
    assert (
        service.ask(f"What was revenue {SCOPE}", "a", PROFILES["analyst-a"], analyst).reason
        == "AMBIGUOUS_METRIC"
    )


def test_trusted_profile_currency_default_is_visible(snapshot_root):
    profile = replace(PROFILES["analyst-a"], default_currency="ZAR")
    result = Service(snapshot_root).ask(
        "Net collected on 1-2 November", "a", profile, ScriptedPlanner()
    )
    assert isinstance(result, Answer) and result.currency_default_used
    assert "ZAR (profile default)" in display(result)


@pytest.mark.parametrize(
    "question,override,reason",
    [
        ("Net collected", {"metric_id": "captured_amount"}, "METRIC_MISMATCH"),
        ("Net collected by day", {}, "GROUP_REQUIRED"),
        ("Net collected by provider", {"grouping": "day"}, "GROUP_REQUIRED"),
        ("Net collected by day and by provider", {}, "GROUP_REQUIRED"),
    ],
)
def test_planner_cannot_change_the_named_metric_or_grouping(
    snapshot_root, question, override, reason
):
    service = Service(snapshot_root, executor=NoQuery())
    answer = service.ask(
        f"{question} {SCOPE}", "a", PROFILES["analyst-a"], RoguePlanner(plan(**override))
    )
    assert (answer.status, answer.reason) == ("clarify", reason)


def test_spelled_date_range_includes_the_last_requested_day(snapshot_root):
    service = Service(snapshot_root)
    answer = ask(service, "net collected", "in ZAR from 1 November to 3 November 2026")
    assert isinstance(answer, Answer)
    assert (answer.start, answer.end, answer.rows[0].value) == (
        date(2026, 11, 1),
        date(2026, 11, 4),
        28000,
    )


@pytest.mark.parametrize(
    "dates",
    ["on 1 November and 3 November", "on 1 and 3 November", "today on 2026-11-01"],
)
def test_ambiguous_date_mentions_do_not_run_a_partial_window(snapshot_root, dates):
    answer = ask(Service(snapshot_root, executor=NoQuery()), "net collected", f"in ZAR {dates}")
    assert (answer.status, answer.reason) == ("clarify", "DATE_REQUIRED")


def test_reader_uses_snapshot_root_relative_to_caller(snapshot_root, monkeypatch):
    monkeypatch.chdir(snapshot_root)
    answer = ask(Service(Path(".")), "net collected")
    assert isinstance(answer, Answer) and answer.rows[0].value == 13000


@pytest.mark.parametrize(
    "mark,reason",
    [
        (None, "MISSING_WATERMARK"),
        (
            Watermark(
                loaded_at=datetime(2026, 11, 5, 9, tzinfo=UTC), complete_through=date(2026, 11, 5)
            ),
            "FUTURE_WATERMARK",
        ),
        (
            Watermark(
                loaded_at=datetime(2026, 11, 5, 7, 50, tzinfo=UTC),
                complete_through=date(2026, 11, 2),
            ),
            "INCOMPLETE_WINDOW",
        ),
    ],
)
def test_freshness_requires_all_input_marks(snapshot_root, monkeypatch, mark, reason):
    from governed_metrics import service as implementation

    current = implementation.metadata

    def replace(path, revision):
        marks = current(path, revision)
        if mark is None:
            del marks["refunds"]
        else:
            marks["refunds"] = mark
        return marks

    monkeypatch.setattr(implementation, "metadata", replace)
    service = Service(snapshot_root, executor=NoQuery())
    assert ask(service, "net collected").reason == reason
    assert ask(Service(snapshot_root), "captured amount").rows[0].value == 17000


def test_parameter_order_binds_tenant_and_currency_in_each_fact_scan():
    statement = compile_metric(MetricPlan.model_validate_json(plan(provider="CARD")))
    assert statement.parameters == ("a", "ZAR", "2026-11-01", "2026-11-03", "CARD") * 2
    assert statement.sql.count("merchant_id = ? and currency = ?") == 2


def test_worker_result_cap_and_timeout(snapshot_root, monkeypatch):
    _, file = pin_snapshot(snapshot_root, "fresh")
    result = execute(
        {
            "snapshot": str(file),
            "threads": 2,
            "memory_mib": 256,
            "statement": "SELECT i FROM range(61) AS rows(i)",
            "parameters": [],
        }
    )
    assert result == {"status": "RESULT_LIMIT"}

    def expired(*args, **kwargs):
        assert "OPENAI_API_KEY" not in kwargs["env"]
        raise subprocess.TimeoutExpired(args[0], 3)

    monkeypatch.setattr(subprocess, "run", expired)
    worker = DuckDBExecutor()
    with pytest.raises(QueryFailure, match="QUERY_TIMEOUT"):
        worker.query(Path("fixture.duckdb"), Statement("example", "SELECT 1", ()))
    assert ask(Service(snapshot_root, executor=worker), "captured amount").model_dump(
        exclude={"trace_id"}
    ) == {"status": "unavailable", "reason": "QUERY_TIMEOUT"}


def test_sixty_days_are_allowed_and_timezone_controls_relative_dates(snapshot_root):
    outcome = ask(
        Service(snapshot_root), "captured amount by day", "ZAR from 2026-09-06 to 2026-11-04"
    )
    assert len(outcome.rows) == 60
    assert outcome.rows[0].group == "2026-09-06"
    assert date_window("yesterday", date(2026, 11, 5)) == (date(2026, 11, 4), date(2026, 11, 5))
    assert date_window("2 december", date(2026, 11, 5)) is None
