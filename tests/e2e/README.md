# `tests/e2e`

Whole sessions on the real runtime and handlers: every `evals/cases/scenarios/S*.yaml` replayed
offline (`test_scenarios.py`, the deterministic release gate), the tracer-bullet acceptance
test through HTTP (`test_api_tracer.py`), and S01 and S12 on Postgres (`test_api_postgres.py`,
`make test-db`).
