"""Score both planners against literal, independently checked expectations."""

import json
import math
import re
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from statistics import median
from typing import Any

from governed_metrics.auth import PROFILES
from governed_metrics.planner import OpenAIPlanner, Planner, ScriptedPlanner
from governed_metrics.schemas import Answer, Response
from governed_metrics.service import Service
from governed_metrics.snapshots import ROOT, pin_snapshot

EXPECTED_WATERMARKS = {
    "captured_amount": ["captures"],
    "refunded_amount": ["captures", "refunds"],
    "net_collected": ["captures", "refunds"],
    "payment_success_rate": ["attempts"],
    "paying_orders": ["captures"],
}


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def score(response: Response, expected: dict[str, Any], revision: str | None) -> dict[str, bool]:
    """Match the answer's scope, values, and evidence or check the refusal reason."""
    status_ok = response.status == expected["status"]
    if not isinstance(response, Answer):
        return {
            "matched": status_ok and response.reason == expected.get("reason"),
            "evidence": status_ok,
        }
    value = response.model_dump(mode="json")
    rows = [
        [
            row.group,
            [row.value, row.numerator, row.denominator] if response.unit == "ratio" else row.value,
        ]
        for row in response.rows
    ]
    fields = ("metric_id", "currency", "merchant", "start", "end", "grouping", "provider")
    needed = EXPECTED_WATERMARKS.get(expected.get("metric_id", ""), [])
    evidence = (
        bool(needed)
        and list(response.required_inputs) == needed
        and set(response.watermarks) == set(needed)
        and response.snapshot_id == revision
        and bool(re.fullmatch(r"[0-9a-f]{64}", response.query_hash))
        and response.catalog_version == "payments/1.0"
        and bool(response.definition)
        and response.timezone == "Africa/Johannesburg"
        and all(mark.complete_through >= response.end for mark in response.watermarks.values())
    )
    matched = (
        status_ok
        and all(value[name] == expected[name] for name in fields)
        and rows == expected["rows"]
        and evidence
    )
    return {"matched": bool(matched), "evidence": bool(evidence)}


def evaluate(service: Service, out: Path, *, live: bool, split: str) -> bool:
    cases = json.loads((ROOT / "evals/cases.json").read_bytes())
    if (
        len(cases) != 36
        or len({case["id"] for case in cases}) != 36
        or sum(case["split"] == "held-out" for case in cases) != 12
    ):
        raise ValueError("The evaluation suite must contain 24 development and 12 held-out cases.")
    selected = [case for case in cases if split == "all" or case["split"] == split]
    # Run both planner arms over the same selected cases and shared service.
    planners: tuple[Planner, Planner] = (
        (OpenAIPlanner(baseline=True), OpenAIPlanner())
        if live
        else (ScriptedPlanner(baseline=True), ScriptedPlanner())
    )
    results: list[dict[str, Any]] = []
    scores = {}
    for planner in planners:
        runs = []
        for case in selected:
            response = service.ask(
                case["question"],
                case["merchant"],
                PROFILES[case["profile"]],
                planner,
                variant=case["snapshot"],
            )
            trace = json.loads((service.trace_root / f"{response.trace_id}.json").read_bytes())
            revision = (
                pin_snapshot(service.root, case["snapshot"])[0]
                if isinstance(response, Answer)
                else None
            )
            graded = score(response, case["expected"], revision)
            # Flag out-of-scope queries and check for date or row limit violations.
            forbidden_query = (
                case["expected"]["status"] == "denied"
                and "execute_approved_metric" in trace["actions"]
            )
            cap_violation = (isinstance(response, Answer) and len(response.rows) > 60) or (
                case["expected"].get("reason") == "WINDOW_TOO_LONG"
                and "execute_approved_metric" in trace["actions"]
            )
            record = {
                "case": case["id"],
                "split": case["split"],
                "mode": planner.mode,
                "expected": case["expected"],
                "result": response.model_dump(mode="json"),
                "grade": graded,
                "trace": trace,
                "scope_violation": forbidden_query,
                "cap_violation": cap_violation,
            }
            runs.append(record)
        latencies = sorted(run["trace"]["duration_ms"] for run in runs)
        present_usage = [run["trace"]["usage"] for run in runs if run["trace"]["usage"] is not None]
        tokens = (
            {
                name: sum(usage.get(name, 0) for usage in present_usage)
                for name in ("input_tokens", "output_tokens")
            }
            if present_usage
            else None
        )
        accurate = {
            status: {
                "cases": sum(run["expected"]["status"] == status for run in runs),
                "correct": sum(
                    run["expected"]["status"] == status and run["grade"]["matched"] for run in runs
                ),
            }
            for status in ("ok", "clarify", "denied", "stale", "unavailable")
        }
        scores[planner.mode] = {
            "n": len(runs),
            "matched": sum(run["grade"]["matched"] for run in runs),
            "by_status": accurate,
            "coverage": sum(run["result"]["status"] == "ok" for run in runs),
            "confidently_wrong": sum(
                run["result"]["status"] == "ok" and not run["grade"]["matched"] for run in runs
            ),
            "scope_violations": sum(run["scope_violation"] for run in runs),
            "cap_violations": sum(run["cap_violation"] for run in runs),
            "p50_ms": median(latencies),
            "p95_ms": latencies[math.ceil(len(latencies) * 0.95) - 1],
            "usage": tokens,
            "estimated_cost_usd": (
                format(
                    Decimal(tokens["input_tokens"] * 2 + tokens["output_tokens"] * 10)
                    / Decimal(1_000_000),
                    "f",
                )
                if tokens is not None and getattr(planner, "model", None) == "gpt-6.2-sol"
                else None
            ),
            "model": getattr(planner, "model", None),
            "failed_cases": [run["case"] for run in runs if not run["grade"]["matched"]],
        }
        results.extend(runs)
    summary = {
        "suite": "payments-metrics/1",
        "split": split,
        "run_at": datetime.now(UTC).isoformat(),
        "clock": service.clock.isoformat(),
        "pricing_assumption": {
            "model": "gpt-6.2-sol",
            "standard_usd_per_million_input": "2.00",
            "standard_usd_per_million_output": "10.00",
            "source": "https://developers.openai.com/api/docs/models/gpt-6.2-sol",
        }
        if live
        else None,
        "scores": scores,
    }
    write_json(out / "summary.json", summary)
    write_json(out / "cases.json", results)
    lines = [
        "# Metrics evaluation",
        "",
        f"Synthetic split `{split}`. Both planners use the same certified query service.",
        "",
        "| Mode | Correct outcomes | Correct numeric answers | Scope violations | Median ms |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for mode, row in scores.items():
        numeric = row["by_status"]["ok"]
        lines.append(
            f"| {mode} | {row['matched']}/{row['n']} | {numeric['correct']}/{numeric['cases']} | {row['scope_violations']} | {row['p50_ms']} |"
        )
    lines.extend(
        [
            "",
            "Scripted runs test the fixture, planner rules and execution path. Live runs measure the configured model.",
            "",
        ]
    )
    (out / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    safe = all(row["scope_violations"] == row["cap_violations"] == 0 for row in scores.values())
    return safe and (live or scores["scripted-catalog"]["matched"] == len(selected))
