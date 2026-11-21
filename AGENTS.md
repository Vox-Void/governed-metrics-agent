# Repository guide

- Keep all fixtures synthetic. Credentials belong in the invoking environment.
- Treat the trusted principal and compiled metric policy as the authority boundary. Keep planners and MCP requests outside it.
- Run the dbt build and the service tests after changes to model grain, bindings, freshness or snapshot publication.
- Keep independent expected answers in the fixture and evaluation files. Grade exact monetary and rate values with the declared evidence.
