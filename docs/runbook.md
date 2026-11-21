# Operator guide

## Ask a question

```bash
./scripts/dev ask --profile analyst-a --merchant a \
  'Net collected in ZAR on 1-2 November 2026'
./scripts/dev list --profile ops-a --merchant a
./scripts/dev template net_collected --group day
```

Add `--json` to inspect the typed answer. The template command returns SQL with placeholders. The simulated operations profile can ask for CARD payment success rate by day or total. It will be asked to confirm CARD if it is absent from the request.

The demo clock is 5 November 2026 at 08:00 UTC. Use ISO dates, a month-day phrase or yesterday. A date phrase without a year uses the current Johannesburg year if the resulting date is today or earlier. A later day without a reliable year requires clarification. A date window can contain up to 60 business dates.

## Review a freshness decision

```bash
./scripts/dev ask --profile analyst-a --merchant a --snapshot stale-refunds \
  'Net collected in ZAR on 1-2 November 2026'
./scripts/dev ask --profile analyst-a --merchant a --snapshot stale-refunds \
  'Captured amount in ZAR on 1-2 November 2026'
```

Each required input has its own load timestamp and exclusive complete-through date. The service requires each watermark to cover the requested window and to have loaded within two hours of its clock. Refund metrics also check capture input freshness because the refund count depends on the referenced capture.

## Isolated reader

After bootstrap, Docker Compose can run the offline reader under a dedicated user. The mount is read-only and the container has no network.

```bash
docker compose build metrics-reader
docker compose run --rm -T metrics-reader ask --root /snapshots --merchant a \
  'Net collected in ZAR on 1-2 November 2026'
```

## MCP stdio tools

Use `./scripts/dev mcp --profile analyst-a` as the local MCP client's command and arguments. The server offers `list_metrics` for scoped discovery and `run_metric` for one structured metric request. Supply `merchant`, `metric_id`, `currency`, `grouping`, `provider` and ISO `start`/`end` dates. Use `null` as the provider when there is no filter. The launcher sets the profile. Stdio tests cover the 2025-11-25 handshake and 2026-07-28 request metadata. [MCP stdio specification](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/stdio)

## Benchmark and optional live mode

Use `./scripts/dev eval --split held-out` for the twelve challenge cases or `./scripts/dev eval` for all 36. Both scripted arms use the same policy and DuckDB queries. The baseline uses certified metric names. The catalog arm also uses approved aliases.

Set `OPENAI_API_KEY` and optionally `GOVERNED_METRICS_MODEL` to run `./scripts/dev eval --mode live --split held-out`. Live mode uses one request per authorized question and a 700-token output cap. The default model is `gpt-6.2-sol`. For that model the report estimates usage at standard token rates. Runtime traces are stored locally with decision paths, duration and token counts. [OpenAI model pricing](https://developers.openai.com/api/docs/models/gpt-6.2-sol)
