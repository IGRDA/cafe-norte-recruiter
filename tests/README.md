# Tests

`make check` runs Ruff, strict mypy and the offline suite: no network, no Postgres, no
credentials. `make test-db` runs the `postgres`-marked tests against the compose database; CI
runs both. `live`-marked tests are paid and manual.

| Layer | What it checks | Needs |
| --- | --- | --- |
| Architecture | Import rules of `src/cafe_norte/README.md`, read from the source | nothing |
| Domain | Field algebra laws (property-based), patch validation, confirmation gating, booking conditions, lifecycle transitions | nothing |
| Conversation | Tool loop bounds, repair budget, persistence before announcement, cancellation, duplicate input ids, explicit controls | `FakeModel`, `MemoryStore`, `FakeRetriever` |
| Knowledge | Front matter, chunking, store filtering before ranking, fusion, abstention fixtures | local index of the fixture KB |
| Persistence | Lease claim/renew/supersede, admission, slot race, idempotent reservation, export snapshot consistency, cleanup lock | Postgres |
| API | Validation without echo, ownership on every endpoint, SSE replay, cookie and resume token rules, security headers | fakes |
| Voice | Bridge behaviour on interruption and delivery acknowledgement | fake processor frames, no Pipecat |

Scenario fixtures `S01`–`S18` from `evals/cases/scenarios/` run here against the fake model as
the deterministic release gate; their live counterparts run from `evals/`.

Fakes live next to the port they implement (`model/fake.py`, `persistence/memory.py`,
`knowledge/fake.py`, `voice/fake.py`); production code never selects them except `main.py`
when the environment asks for them.
