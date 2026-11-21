# Example results

The [Linux CI run](https://github.com/Vox-Void/governed-metrics-agent/actions/runs/44920687987) built the dbt models, ran the service tests and produced the [demo evidence](demo.json), [benchmark summary](eval-summary.json), [per-case outcomes](eval-cases.json) and [isolated reader answer](isolated-answer.json).

The scripted benchmark uses 24 development cases and 12 held-out cases. Both planners use the same identities, snapshots and query service. The baseline recognizes metric names and the catalog planner also recognizes the approved aliases and currency wording.

| Planner | Correct outcomes | Exact numerical answers | Correct clarifications | Correct denials | Correct stale results |
| --- | ---: | ---: | ---: | ---: | ---: |
| Scripted baseline | 29/36 | 19/26 | 6/6 | 2/2 | 1/1 |
| Scripted catalog | 36/36 | 26/26 | 6/6 | 2/2 | 1/1 |

Both arms had zero scope and cap violations. The baseline's seven misses were held-out questions using alternative metric or currency wording. It withheld results on those questions. The catalog planner matched the expected values, dates and evidence for all seven. These scores measure the scripted rules on the named fixture questions.

## Problems found during testing

- The first reader connection tried to set DuckDB's time-zone option with extension autoloading disabled. The reader now converts persisted epoch microseconds to UTC directly. The dbt models still compute business dates at build time.
- The initial plan checks could accept a planner-supplied CARD filter even when the operations reader had not requested it. The service now asks the reader to confirm CARD. It also checks the requested currency and date window before compiling SQL.
- Duplicate refunds can multiply capture money in a direct join. The fixture retains both refunds and a separate refund for an older capture. The compiler binds the authorized scope on each stream and aggregates the two streams independently. The golden result is 13,000 ZAR minor units.

The data tests also exercise an actual failed build and a parallel read during staged publication. The first preserves the published revision. The second checks that old and new answers each match their own revision.
