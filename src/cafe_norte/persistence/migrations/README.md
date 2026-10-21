# SQL migrations

Numbered, forward-only `NNNN_name.sql` files, applied in name order by
`cafe_norte.persistence.migrate.apply_pending` under one advisory lock and recorded in
`schema_migrations`, a table the applier creates itself. `PostgresStore.open()` applies what is
pending before the app serves; `make migrate` runs the same function by hand.

Each file runs in one transaction through the simple query protocol: several statements per
file are fine, parameters are not (there are none), and a failing file is rolled back whole and
stops the run. A migration that must survive a rollback to the previous image is written
backward compatible (add, backfill, switch, drop later).

`0001_initial.sql` holds the tables of the first Postgres pull request: sessions (one JSONB
document with generated columns), turns, events, interview slots, bookings, usage and timings.
Leases, admission, resume tokens, summary jobs and export snapshots arrive with their stages
and are listed in its header comment.
