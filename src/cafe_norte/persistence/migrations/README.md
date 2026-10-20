# SQL migrations

Numbered, forward-only, applied by `cafe_norte.persistence.migrate` under an advisory lock and
recorded in `schema_migrations`. A migration that must support rollback to the previous image
is written backward compatible (add, backfill, switch, drop later).

`0001_initial.sql` outlines the tables the spec requires; it is filled in when the Postgres
adapter lands.
