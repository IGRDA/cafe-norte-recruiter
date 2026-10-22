# Working conventions for this repository

Read `docs/DECISIONS.md` before changing structure; a decision there is not re-litigated in a
pull request. Read `src/cafe_norte/README.md` for the module map and import rules.

- Code, comments, docs and commit messages in English. Candidate-facing text in Spanish (Spain)
  and English, only in `errors.py` and `conversation/prompts/`.
- Types: frozen Pydantic models for records, `Protocol` for ports, `Literal` unions for enums,
  `Result` for domain refusals. No `Any` outside JSON payload fields. Strict mypy stays green.
- Pure domain. `domain/` takes values and returns values; time is an argument.
- Fakes are first-class and live beside the port they implement. `make check` never needs
  credentials, Docker or network.
- Every directory keeps its README current. Every behaviour has a test; every limit a number
  in `docs/architecture.md`.
- Nothing is announced to a candidate before it is persisted. No value is ever guessed into a
  field.
- Commit messages: `area: what changed` (imperative), body explains why when it is not obvious.
- Before a merge: `make preflight` green (checks, Postgres suite, live scenarios with the
  behavioural invariants) and Iñaki's OK after calling `make preview` (D64). A local check on the
  memory store is not a check: production runs on Postgres.
