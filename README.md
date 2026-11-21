# Governed Metrics Agent

Ask for a certified payments metric and see the value, definition, scope and freshness used to answer it. The fixture uses synthetic capture, refund and attempt deliveries.

Watch the [2:18 captioned demo](docs/demo.mp4) for the net collection answer, revenue clarification, access denial and stale-refund case.

## Run it

Use Bash on Linux or WSL2 with `uv` 0.13.9. Run these commands from the repository root.

```bash
./scripts/dev bootstrap
./scripts/dev test
./scripts/dev demo
./scripts/dev eval
```

Bootstrap downloads the locked dependencies, then seeds and builds six dbt models. After seven dbt tests pass, it publishes a fresh snapshot and a stale-refund example under `artifacts/`. The default demo and evaluation run without an API key.

## What the demo shows

| Question or request | Outcome |
| --- | --- |
| What did Merchant A collect after refunds in ZAR on 1-2 November? | **ZAR 130.00**, with the certified definition, business-date window, catalog version and freshness evidence. |
| How much revenue did we make? | A question asking whether you mean gross captured amount or net collected after refunds. |
| Can the Merchant A profile read Merchant B's net collection? | A scope denial before the planner or query runs. |
| What happens when the refund input is stale? | Net collected is withheld. Captured amount is still **ZAR 170.00** for the same window. |

The report is saved to `artifacts/demo.json`. The evaluation saves its aggregate scores and decisions under `artifacts/eval/`.

## How a certified answer is produced

1. dbt validates delivery versions, composite IDs, payment state and references. It builds canonical capture, refund and attempt tables with explicit contracts.
2. The service checks the trusted profile against the requested merchant before exposing a catalog or calling a planner. The planner proposes a metric, date window and grouping or asks a question.
3. The service rechecks the proposed scope and freshness, pins a tested snapshot, and executes one approved query with bound parameters. Net collected uses separate capture and refund aggregates.
4. The response contains the calculation and its provenance. The same rules apply to the terminal and MCP tools.

See the [operator guide](docs/runbook.md) for profile examples, live mode and the isolated reader. The [architecture](docs/architecture.md) explains the facts, snapshot publication and authority boundary. The [example results](docs/example-results/README.md) cover the benchmark and problems found during testing. The [review pull request](https://github.com/Vox-Void/governed-metrics-agent/pull/1) contains the service and its regression tests.
