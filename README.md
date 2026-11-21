# Governed Metrics Agent

Ask for a certified payments metric and see the value, definition, scope and freshness used to answer it. The fixture uses synthetic capture, refund and attempt deliveries.

## Build a snapshot

Use Bash on Linux or WSL2 with `uv` 0.13.9. Run `./scripts/dev bootstrap` from the repository root. The first build downloads the locked Python dependencies. It then seeds, builds and tests the dbt models in DuckDB. After all seven dbt tests pass, it publishes a fresh snapshot and a stale-refund example under `artifacts/`.
