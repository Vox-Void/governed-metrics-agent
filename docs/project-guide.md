# How the Governed Metrics Agent works

Ask what Merchant A collected after refunds in ZAR on 1 and 2 November 2026. The demo answers **ZAR 130.00**. You can check that number against the original payment files and see which version of the data the answer came from. The [demo output](example-results/demo.json) includes the full answer.

## Building the payment data

The build starts with three small CSVs. A capture records money taken from a customer. A refund records money returned on a capture. An attempt records the state of a payment, including failures and payments still pending. The fixture has repeated deliveries, shared IDs across merchants, and refunds that settle on a different day from the capture. Those rows make mistakes visible in a small set of numbers. You can compare the [seed files](../data/seeds) with the [expected totals](../data/goldens.json).

dbt loads the CSVs into DuckDB. Three staging models cast the raw values, then three fact models select the current record for each capture, refund, or attempt. The key includes the merchant. Both merchants have a capture called `c1`, and Merchant A's `c1` arrives twice with the same values. The capture model retains one record for each merchant. It also turns Merchant A's settlement time of 22:10 UTC on 31 October into 1 November in Johannesburg. See the [staging models](../dbt_project/models/staging) and [capture model](../dbt_project/models/marts/fct_captures.sql).

Seven dbt tests check versions, event keys, allowed values, timestamps, and references between records. They also check that the sum of settled refunds on a capture stays within the original capture amount. The build saves the facts and input timestamps together in revisioned files. It replaces `current.json` after both files are in place, and each request opens one revision. Once a revision is published, readers keep using it until another build passes and publishes. The checks and publication code are in the [dbt tests](../dbt_project/tests) and [snapshot builder](../src/governed_metrics/snapshots.py).

## Following the ZAR 130.00 answer

1. **Check the merchant.** The launcher selects the `analyst-a` profile. The service checks that this profile can read Merchant A before it loads the catalog or asks the planner. The terminal and MCP tools go through the same service. The relevant code is in the [profiles](../src/governed_metrics/auth.py), [service](../src/governed_metrics/service.py), and [MCP adapter](../src/governed_metrics/mcp.py).
2. **Read the question.** The scripted planner matches “collected after refunds” to `net_collected`. It reads ZAR and converts the two requested business days into a range from 1 November up to, and excluding, 3 November. The service checks the plan against the profile and the question before it opens the snapshot. Follow the match and the output it produces in the [metric catalog](../metrics/catalog.yml), [planner](../src/governed_metrics/planner.py), and [plan schema](../src/governed_metrics/schemas.py).
3. **Check when the inputs arrived.** Net collection needs both captures and refunds. The demo clock is 08:00 UTC on 5 November. In the fresh snapshot, both inputs were loaded at 07:50 UTC and cover the whole requested range. `run_plan` applies these checks in the [service](../src/governed_metrics/service.py), using the snapshot values drawn from the [fixture watermarks](../data/freshness.json).
4. **Calculate the amount.** The SQL compiler puts the merchant, currency, and dates into parameters for both scans. Three settled captures add up to ZAR 170.00. Three settled refunds add up to ZAR 40.00, including a refund from an earlier capture. The query adds up each set of rows separately and subtracts the refunds. Joining captures straight to refunds would count Merchant A's `c1` twice because it has two settled refunds in this window. The code for this calculation lives in the [compiler](../src/governed_metrics/compiler.py) and the [query worker](../src/governed_metrics/worker.py).
5. **Show the evidence.** The service formats the answer from 13,000 cents and attaches the definition, dates, merchant, input timestamps, and snapshot ID. It also returns the name and hash of the SQL template. Use `--json` to see those fields. See the [operator guide](runbook.md) for runnable examples.

## When the answer changes

- “How much revenue did we make?” could mean gross captures or net collections. The service returns a question to clarify which measure the reader wants.
- Asking for Merchant B with `analyst-a` returns a scope denial before planning or querying. The same applies to an unknown merchant.
- In the stale-refund snapshot, refunds were loaded at 03:00 UTC. That falls outside the two-hour freshness window at the demo clock. The service withholds net collection and can still return ZAR 170.00 for captures.

The test suite checks the amounts and those decisions. It also exercises a failed dbt build and a read during publication to check that each answer belongs to a single revision. The scripted benchmark uses 36 questions, including variants that use different wording for the same measure. The details are in the [publication tests](../tests/test_publish.py) and [benchmark results](example-results/README.md).
