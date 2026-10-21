# `persistence`: Postgres is the source of truth

The runtime never claims an update, a confirmation or a reservation until the transaction that
stores it has committed. Ownership leases, admission slots, slot reservations and idempotency
keys are all rows with constraints; a second container cannot win a race the database already
decided.

| File | Contents |
| --- | --- |
| `contracts.py` | Repository ports (`Sessions`, `Turns`, `Events`, `Calendar`, `Leases`, `Admission`, `SummaryJobs`, `Exports`, `ResumeTokens`), `Transaction` and `Store` ports |
| `postgres/` | psycopg 3 implementation (D31). `store.py`: the pool (five connections, statement and lock timeouts set at connect), the transaction boundary, readiness, the repeatable-read `snapshot`; `support.py`: the only place psycopg errors become `ServiceError` codes, plus the row fetchers; `codecs.py`: pure record/row functions, the only place that names columns; `sessions.py` (one JSONB document with generated columns, conditional `save` and `next_seq`, both fenced on the lease generation), `turns.py`, `events.py` (polling `since`), `calendar.py` (row-locked `reserve`), `leases.py` (one row per session, generation grows on every claim, release expires it), `admission.py` (voice places as rows under a table lock, aged out by a ttl), `resume_tokens.py` (hashes only, reusable until expiry), `exports.py` (one snapshot per session, stored at close) |
| `memory.py` | In-memory implementation for offline tests and local runs: buffered transactions, revision and input-id checks at commit, live `since` stream, a calendar with one booking per slot and per session and idempotent `reserve` (checked at enlist and at commit; `clock` stands in for `now()`), leases and the fence, a per-process admission set, resume tokens |
| `later.py` | The narrative summary job, optional and not built: both stores raise `NotImplementedError` |
| `retention.py` | `purge_expired` (the oldest sessions beyond the window, a batch at a time, under `Store.maintenance()`) and `purge_periodically`, the lifespan task (D34) |
| `seed.py` | `seed_calendar(store, configurations, now)`: inserts the slots `domain.calendar.interview_slots` generates; idempotent by construction |
| `migrate.py` | `apply_pending(dsn)`: applies `migrations/*.sql` in order under one advisory lock and records them in `schema_migrations`, which it creates itself. Run by `PostgresStore.open()` at startup and by `make migrate` |
| `migrations/` | Numbered SQL files; backward compatible when a rollback to the previous image must work |
| `export.py` | `ExportDocument` (the published JSON Schema), `build_export(snapshot)`, pure over one `Store.snapshot` read, and `persist_export`, the close hook that stores it. The confirmation history and the session's end are read from the journaled `state_updated` events; the brief is the text the candidate confirmed; cost stays `None` until prices are recorded |

The store is chosen in `main.py`: `CAFE_NORTE_DATABASE_URL` set means Postgres, empty means
memory (D31). Locally it is the compose database (`make db-up`); the hosted demo reaches Cloud SQL through
the Auth Proxy on the VM (D33). One built-in user applies the migrations and serves the app.

The store contract is one test suite over both implementations: `tests/test_store_contract.py`
and `tests/test_calendar_contract.py` run on the memory store in `make check` and on Postgres
in `make test-db`, through the `store` fixture of `tests/conftest.py`.
