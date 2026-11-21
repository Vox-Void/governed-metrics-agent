"""Build and inspect the certified payments fixture."""

import argparse
import json
import os
from pathlib import Path

from governed_metrics.auth import PROFILES
from governed_metrics.catalog import load_catalog
from governed_metrics.compiler import compile_metric
from governed_metrics.evaluation import evaluate, write_json
from governed_metrics.mcp import serve
from governed_metrics.planner import OpenAIPlanner, ScriptedPlanner
from governed_metrics.schemas import METRICS, PROVIDERS, MetricPlan
from governed_metrics.service import Service, display
from governed_metrics.snapshots import VARIANTS, SnapshotError, publish_snapshots


def demo(service: Service, path: Path) -> bool:
    cases = (
        ("How much did we collect after refunds in ZAR on 1-2 November 2026?", "a", "fresh", "ok"),
        ("How much revenue in ZAR on 1-2 November 2026?", "a", "fresh", "clarify"),
        ("Net collected in ZAR on 1-2 November 2026", "b", "fresh", "denied"),
        ("Net collected in ZAR on 1-2 November 2026", "a", "stale-refunds", "stale"),
        ("Captured amount in ZAR on 1-2 November 2026", "a", "stale-refunds", "ok"),
    )
    rows = []
    passed = True
    for question, merchant, variant, expected in cases:
        result = service.ask(
            question, merchant, PROFILES["analyst-a"], ScriptedPlanner(), variant=variant
        )
        rendered = display(result)
        rows.append(
            {
                "question": question,
                "merchant": merchant,
                "snapshot_variant": variant,
                "formatted": rendered,
                "answer": result.model_dump(mode="json"),
            }
        )
        print(f"\n{question}\n{rendered}")
        passed = passed and result.status == expected
    write_json(path, {"mode": "scripted-catalog", "cases": rows})
    print(f"\nReport {path}")
    return passed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    bootstrap = commands.add_parser("bootstrap")
    bootstrap.add_argument("--out", type=Path, default=Path("artifacts"))
    for name in ("ask", "list", "demo", "eval", "mcp"):
        command = commands.add_parser(name)
        command.add_argument("--root", type=Path, default=Path("artifacts"))
        if name in {"ask", "list", "mcp"}:
            command.add_argument("--profile", choices=tuple(PROFILES), default="analyst-a")
        if name in {"ask", "list"}:
            command.add_argument("--merchant", required=True)
        if name in {"ask", "eval"}:
            command.add_argument("--mode", choices=("scripted", "live"), default="scripted")
        if name in {"ask", "mcp"}:
            command.add_argument("--snapshot", choices=VARIANTS, default="fresh")
        if name == "ask":
            command.add_argument("question")
            command.add_argument("--json", action="store_true")
        if name == "eval":
            command.add_argument(
                "--split", choices=("all", "development", "held-out"), default="all"
            )
    template = commands.add_parser("template")
    template.add_argument("metric", choices=METRICS)
    template.add_argument("--group", choices=("total", "day", "provider"), default="total")
    template.add_argument("--provider", choices=PROVIDERS)
    args = parser.parse_args()
    if getattr(args, "mode", None) == "live" and not os.environ.get("OPENAI_API_KEY"):
        parser.error("Set OPENAI_API_KEY to opt into the live planner.")
    if args.command == "template":
        if args.group not in load_catalog().metrics[args.metric].groups:
            parser.error("This metric does not support that grouping.")
        plan = MetricPlan.model_validate_json(
            json.dumps(
                {
                    "kind": "plan",
                    "metric_id": args.metric,
                    "merchant": "a",
                    "currency": "ZAR",
                    "start": "2026-11-01",
                    "end": "2026-11-03",
                    "grouping": args.group,
                    "provider": args.provider,
                }
            )
        )
        print(compile_metric(plan).sql)
        return 0
    try:
        if args.command == "bootstrap":
            print(json.dumps(publish_snapshots(args.out), indent=2))
            return 0
        service = Service(args.root)
        if args.command == "demo":
            return 0 if demo(service, args.root / "demo.json") else 1
        if args.command == "eval":
            return (
                0
                if evaluate(service, args.root / "eval", live=args.mode == "live", split=args.split)
                else 1
            )
        profile = PROFILES[args.profile]
        if args.command == "mcp":
            serve(service, profile, args.snapshot)
            return 0
        if args.command == "list":
            print(json.dumps(service.discover(args.merchant, profile), indent=2))
            return 0
        planner = OpenAIPlanner() if args.mode == "live" else ScriptedPlanner()
        response = service.ask(
            args.question, args.merchant, profile, planner, variant=args.snapshot
        )
        print(response.model_dump_json(indent=2) if args.json else display(response))
    except SnapshotError as error:
        parser.exit(1, f"{error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
