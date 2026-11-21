"""Authorize scope, pin a snapshot, and answer from one approved statement."""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, localcontext
from pathlib import Path
from time import monotonic
from typing import Any
from uuid import uuid4

import duckdb
from pydantic import ValidationError

from governed_metrics.auth import Principal
from governed_metrics.catalog import Catalog, MetricDefinition, load_catalog
from governed_metrics.compiler import compile_metric
from governed_metrics.executor import DuckDBExecutor, Executor, QueryFailure
from governed_metrics.planner import (
    Context,
    Planner,
    ambiguous_reason,
    business_today,
    date_window,
    recognised_metrics,
    requested_currencies,
    requested_providers,
)
from governed_metrics.schemas import (
    CLARIFICATIONS,
    DECISION,
    PROVIDERS,
    Answer,
    Clarification,
    ClarificationCode,
    Clarify,
    Failure,
    Grouping,
    MetricPlan,
    MetricRow,
    Response,
    Unable,
    Watermark,
)
from governed_metrics.snapshots import DEMO_CLOCK, SnapshotError, pin_snapshot
from governed_metrics.worker import connect_read_only


def clarification(trace: str, reason: ClarificationCode) -> Clarify:
    return Clarify(trace_id=trace, reason=reason, question=CLARIFICATIONS[reason])


def denial(trace: str) -> Failure:
    return Failure(status="denied", trace_id=trace, reason="SCOPE_DENIED")


def check_question(text: str, context: Context, plan: MetricPlan) -> ClarificationCode | None:
    """Check metric ambiguity and compare the question's currency, dates, and providers with the plan."""
    choices = recognised_metrics(text, context, baseline=False)
    if len(choices) > 1:
        return "MULTIPLE_METRICS"
    if not choices and (reason := ambiguous_reason(text, context.ambiguous)):
        return reason
    currencies = requested_currencies(text)
    if (currencies and currencies != {plan.currency}) or (
        not currencies and context.currency_default != plan.currency
    ):
        return "CURRENCY_REQUIRED"
    if date_window(text, context.today) != (plan.start, plan.end):
        return "DATE_REQUIRED"
    providers = requested_providers(text)
    if not providers and plan.provider is not None:
        return "PROVIDER_REQUIRED"
    if len(providers) == 1 and plan.provider != providers[0]:
        return "PROVIDER_REQUIRED"
    if len(providers) > 1 and (plan.grouping != "provider" or plan.provider is not None):
        return "PROVIDER_REQUIRED"
    return None


def metadata(path: Path, revision: str) -> dict[str, Watermark]:
    """Check the file's certified revision and return complete input watermarks in UTC."""
    with connect_read_only(path) as connection:
        if connection.execute("select revision, tested from snapshot_meta").fetchall() != [
            (revision, True)
        ]:
            raise SnapshotError("The pinned snapshot has no certified revision.")
        rows = connection.execute(
            "select input, epoch_us(loaded_at), complete_through from input_watermarks"
        ).fetchall()
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    return {
        name: Watermark(loaded_at=epoch + timedelta(microseconds=loaded), complete_through=complete)
        for name, loaded, complete in rows
        if loaded is not None and complete is not None
    }


def ratio(numerator: int, denominator: int) -> str | None:
    if denominator == 0:
        return None
    with localcontext() as context:
        context.prec = 40
        return format(
            (Decimal(numerator) / Decimal(denominator)).quantize(
                Decimal("0.000001"), rounding=ROUND_HALF_UP
            ),
            "f",
        )


def shape_rows(
    plan: MetricPlan, definition: MetricDefinition, rows: list[list[Any]]
) -> list[MetricRow]:
    # Build the ordered list of groups from the request.
    if plan.grouping == "day":
        groups: list[str | None] = [
            (plan.start + timedelta(days=offset)).isoformat()
            for offset in range((plan.end - plan.start).days)
        ]
    elif plan.grouping == "provider":
        groups = [
            provider for provider in PROVIDERS if plan.provider is None or provider == plan.provider
        ]
    else:
        groups = [None]
    by_group = {}
    is_rate = definition.unit == "ratio"
    if len(rows) > 60:
        raise QueryFailure("RESULT_LIMIT")
    # Check the worker's row shape and index each row by its group.
    for row in rows:
        if (
            len(row) != (3 if is_rate else 2)
            or row[0] not in groups
            or row[0] in by_group
            or any(type(value) is not int for value in row[1:])
        ):
            raise QueryFailure("WORKER_RESULT_INVALID")
        by_group[row[0]] = row[1:]
    results = []
    # Fill missing amount and count groups with zero. An empty rate is null with counts of zero.
    for group in groups:
        if is_rate:
            numerator, denominator = by_group.get(group, [0, 0])
            if numerator < 0 or denominator < numerator:
                raise QueryFailure("WORKER_RESULT_INVALID")
            results.append(
                MetricRow(
                    group=group,
                    value=ratio(numerator, denominator),
                    numerator=numerator,
                    denominator=denominator,
                )
            )
        else:
            results.append(MetricRow(group=group, value=by_group.get(group, [0])[0]))
    return results


@dataclass
class Trace:
    mode: str
    trace_id: str = field(default_factory=lambda: uuid4().hex)
    started: float = field(default_factory=monotonic)
    actions: list[str] = field(default_factory=list)
    usage: dict[str, int] | None = None


class Service:
    def __init__(
        self,
        root: Path,
        *,
        clock: datetime = DEMO_CLOCK,
        executor: Executor | None = None,
        trace_root: Path | None = None,
    ):
        if clock.utcoffset() is None:
            raise ValueError("The business clock must include an offset.")
        self.root = root
        self.trace_root = trace_root if trace_root is not None else root / "traces"
        self.clock = clock
        self.executor = executor if executor is not None else DuckDBExecutor()

    def discover(self, merchant: str, principal: Principal) -> dict[str, Any]:
        """Return the metrics, groupings, and providers available to this profile."""
        if merchant != principal.merchant:
            return denial(uuid4().hex).model_dump(mode="json")
        catalog = load_catalog()
        allowed = {
            metric: definition.model_dump()
            for metric, definition in catalog.metrics.items()
            if metric in principal.metrics
        }
        for definition in allowed.values():
            definition["groups"] = [
                group for group in definition["groups"] if group in principal.groups
            ]
        return {
            "status": "ok",
            "catalog_version": catalog.version,
            "timezone": catalog.timezone,
            "metrics": allowed,
            "providers": [
                provider for provider in catalog.providers if provider in principal.providers
            ],
        }

    def close(self, response: Response, trace: Trace) -> Response:
        """Write the decision path, timings, and token counts for one request."""
        record = {
            "trace_id": trace.trace_id,
            "mode": trace.mode,
            "status": response.status,
            "reason": response.reason,
            "actions": trace.actions,
            "usage": trace.usage,
            "duration_ms": round((monotonic() - trace.started) * 1000),
        }
        directory = self.trace_root
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{trace.trace_id}.json").write_text(
            json.dumps(record, indent=2) + "\n", encoding="utf-8"
        )
        return response

    def ask(
        self,
        question: str,
        merchant: str,
        principal: Principal,
        planner: Planner,
        *,
        variant: str = "fresh",
    ) -> Response:
        trace = Trace(planner.mode)
        trace.actions.append("authorize_scope")
        if merchant != principal.merchant:
            return self.close(denial(trace.trace_id), trace)
        if not question.strip() or len(question.encode()) > 4000:
            return self.close(
                Failure(status="unavailable", trace_id=trace.trace_id, reason="QUESTION_LIMIT"),
                trace,
            )
        catalog = load_catalog()
        order: tuple[Grouping, ...] = ("total", "day", "provider")
        # Pass only the profile's metric definitions and groupings to the planner.
        context = Context(
            merchant,
            {
                metric: definition
                for metric, definition in catalog.metrics.items()
                if metric in principal.metrics
            },
            tuple(group for group in order if group in principal.groups),
            principal.default_currency,
            business_today(self.clock),
            tuple(catalog.ambiguous),
        )
        trace.actions.append("propose_plan")
        try:
            suggestion = planner.propose(question, context)
            trace.usage = suggestion.usage
            decision = DECISION.validate_json(suggestion.payload)
        except (ValidationError, OSError, ValueError, TypeError):
            return self.close(
                Failure(status="unavailable", trace_id=trace.trace_id, reason="INVALID_PLAN"), trace
            )
        if isinstance(decision, Clarification):
            response: Response = clarification(trace.trace_id, decision.reason)
        elif isinstance(decision, Unable):
            response = Failure(
                status="unavailable", trace_id=trace.trace_id, reason=decision.reason
            )
        else:
            response = self.run_plan(
                merchant,
                principal,
                decision,
                catalog,
                variant,
                trace,
                natural_request=(question.lower(), context),
            )
        return self.close(response, trace)

    def structured(
        self, payload: str, merchant: str, principal: Principal, *, variant: str = "fresh"
    ) -> Response:
        trace = Trace("structured")
        trace.actions.append("authorize_scope")
        if merchant != principal.merchant:
            return self.close(denial(trace.trace_id), trace)
        try:
            plan = MetricPlan.model_validate_json(payload)
        except ValidationError:
            return self.close(
                Failure(status="unavailable", trace_id=trace.trace_id, reason="INVALID_PLAN"), trace
            )
        return self.close(
            self.run_plan(merchant, principal, plan, load_catalog(), variant, trace), trace
        )

    def run_plan(
        self,
        merchant: str,
        principal: Principal,
        plan: MetricPlan,
        catalog: Catalog,
        variant: str,
        trace: Trace,
        *,
        natural_request: tuple[str, Context] | None = None,
    ) -> Response:
        trace_id = trace.trace_id
        trace.actions.append("authorize_plan")
        # Check the proposed merchant, metric, grouping, and provider against the profile.
        if (
            merchant != principal.merchant
            or plan.merchant != merchant
            or plan.metric_id not in principal.metrics
            or plan.grouping not in principal.groups
            or (plan.provider is not None and plan.provider not in principal.providers)
        ):
            return denial(trace_id)
        confirmed_provider = plan.provider is not None and (
            natural_request is None or plan.provider in requested_providers(natural_request[0])
        )
        if len(principal.providers) < len(PROVIDERS) and not confirmed_provider:
            return clarification(trace_id, "CONFIRM_PROVIDER")
        if plan.end <= plan.start:
            return clarification(trace_id, "DATE_REQUIRED")
        if (plan.end - plan.start).days > 60:
            return clarification(trace_id, "WINDOW_TOO_LONG")
        definition = catalog.metrics[plan.metric_id]
        if plan.grouping not in definition.groups:
            return clarification(trace_id, "UNSUPPORTED_GROUP")
        default_used = False
        if natural_request:
            text, context = natural_request
            if reason := check_question(text, context, plan):
                return clarification(trace_id, reason)
            default_used = not requested_currencies(text)
        trace.actions.append("check_freshness")
        try:
            # Use the same revision for the watermark read and the fact query below.
            revision, path = pin_snapshot(self.root, variant)
            marks = metadata(path, revision)
        except (SnapshotError, duckdb.Error, ValidationError, OSError):
            return Failure(status="unavailable", trace_id=trace_id, reason="SNAPSHOT_UNAVAILABLE")
        required = tuple(definition.inputs)
        # Check the age and date coverage of every input named in the metric definition.
        for source in required:
            mark = marks.get(source)
            if mark is None:
                return Failure(status="stale", trace_id=trace_id, reason="MISSING_WATERMARK")
            age = self.clock - mark.loaded_at
            if age < timedelta(0) or mark.complete_through > business_today(self.clock):
                return Failure(status="stale", trace_id=trace_id, reason="FUTURE_WATERMARK")
            if age > timedelta(hours=2):
                return Failure(status="stale", trace_id=trace_id, reason="STALE_INPUT")
            if mark.complete_through < plan.end:
                return Failure(status="stale", trace_id=trace_id, reason="INCOMPLETE_WINDOW")
        statement = compile_metric(plan)
        trace.actions.append("execute_approved_metric")
        try:
            rows = shape_rows(plan, definition, self.executor.query(path, statement))
        except QueryFailure as error:
            return Failure(status="unavailable", trace_id=trace_id, reason=str(error))
        return Answer(
            trace_id=trace_id,
            metric_id=plan.metric_id,
            label=definition.label,
            definition=definition.definition,
            catalog_version=catalog.version,
            unit=definition.unit,
            currency=plan.currency,
            currency_default_used=default_used,
            merchant=plan.merchant,
            provider=plan.provider,
            grouping=plan.grouping,
            timezone=catalog.timezone,
            start=plan.start,
            end=plan.end,
            rows=rows,
            template_id=statement.template_id,
            query_hash=statement.digest,
            snapshot_id=revision,
            required_inputs=required,
            watermarks={source: marks[source] for source in required},
        )


def display(response: Response) -> str:
    """Format a clarification, a refusal, or a typed answer for the terminal."""
    if isinstance(response, Clarify):
        return response.question
    if isinstance(response, Failure):
        return {
            "denied": "That scope is unavailable for this profile.",
            "stale": "A required input is stale or incomplete for the requested dates.",
            "unavailable": "A certified answer is unavailable for this request.",
        }[response.status]
    lines = []
    for row in response.rows:
        if response.unit == "minor_units" and isinstance(row.value, int):
            major, cents = divmod(abs(row.value), 100)
            sign = "-" if row.value < 0 else ""
            value = f"{response.currency} {sign}{major:,}.{cents:02}"
        elif response.unit == "ratio":
            value = (
                f"{row.value} ({row.numerator}/{row.denominator})"
                if row.value is not None
                else "No terminal attempts (0/0)"
            )
        else:
            value = str(row.value)
        lines.append(
            f"{row.group}  {value}" if row.group is not None else f"{response.label}  {value}"
        )
    currency = response.currency + (" (profile default)" if response.currency_default_used else "")
    scope = f"Merchant {response.merchant.upper()} | {currency} | {response.provider or 'all providers'}"
    return "\n".join(
        [
            *lines,
            response.definition,
            scope,
            f"Window [{response.start}, {response.end})  {response.timezone}",
            f"Catalog {response.catalog_version} | Snapshot {response.snapshot_id}",
            *(
                f"{name} loaded {mark.loaded_at.isoformat()} | complete through {mark.complete_through} (exclusive)"
                for name, mark in response.watermarks.items()
            ),
        ]
    )
