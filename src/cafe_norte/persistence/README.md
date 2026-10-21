# `persistence`: Postgres is the source of truth

The runtime never claims an update, a confirmation or a reservation until the transaction that
stores it has committed. Ownership leases, admission slots, slot reservations and idempotency
keys are all rows with constraints; a second container cannot win a race the database already
decided.

| File | Contents |
| --- | --- |
| `contracts.py` | Repository ports (`Sessions`, `Turns`, `Events`, `Calendar`, `Leases`, `Admission`, `SummaryJobs`, `Exports`, `ResumeTokens`), `Transaction` and `Store` ports |
| `postgres.py` | psycopg 3 async pool implementation; short statement and lock timeouts; at most five connections per container |
| `memory.py` | In-memory implementation for offline tests and local runs: buffered transactions, revision and input-id checks at commit, live `since` stream, a calendar with one booking per slot and per session and idempotent `reserve` (checked at enlist and at commit; `clock` stands in for `now()`). Leases, jobs, tokens and exports raise until their stage |
| `seed.py` | `seed_calendar(store, configurations, now)`: inserts the slots `domain.calendar.interview_slots` generates; idempotent by construction |
| `migrate.py` | Applies `migrations/*.sql` in order under an advisory lock; records versions in `schema_migrations` |
| `migrations/` | Numbered SQL files; backward compatible when a rollback to the previous image must work |
| `export.py` | `ExportDocument` (the published JSON Schema) and `build_export(snapshot)`, pure over one `Store.snapshot` read. The confirmation history and the session's end are read from the journaled `state_updated` events; the brief is the text the candidate confirmed; cost stays `None` until prices are recorded |

Connectivity on Cloud Run uses the built-in Cloud SQL Unix socket (`/cloudsql/<connection>`),
which psycopg speaks natively; locally it is the compose database. Credentials come from
Secret Manager; the migration role is separate from the runtime role.
