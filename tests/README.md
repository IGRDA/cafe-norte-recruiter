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
| Persistence | The store contract (transactions, conditional save, input ids, the event stream and sequence, the slot race, idempotent reservation, the snapshot, leases and fenced writes, admission, resume tokens, export snapshots, expiry and cascading delete, the maintenance lock) on both stores through the `store` fixture; the retention purge (`tests/test_retention.py`); the pure row codecs (property-based); migrations from scratch; database timeouts as error codes; S01 end to end on Postgres with a restart; S12 (restart, zombie lease, resume) on Postgres; S13 through the API with fakes | memory in `make check`; Postgres in `make test-db` |
| API | Validation without echo, ownership on every endpoint, SSE replay, cookie and resume token rules, security headers | fakes |
| Voice | Delivery ledger (pure), `VoiceSession` with a fake runtime and fast timers, the two processors with Pipecat frames in memory, Daily REST with a scripted transport, the voice routes with fakes | Pipecat installed (dev extra), no provider |

Scenario fixtures `S01`–`S18` from `evals/cases/scenarios/` run here against the fake model as
the deterministic release gate; their live counterparts run from `evals/`.

Today (D18) the suite has: the import-rule check, field algebra properties, patch validation
and application, configuration loading, the store contract on both stores, the registry, the
runtime's turn behaviour, SSE encoding and heartbeat, cookie ownership, the Groq adapter
against a scripted transport, the handlers (including the interview offer, slot read-back and reservation), the confirmation rules, the brief, the explicit controls and the signal classifier (`tests/test_signals.py`, with property tests), the slot-choice matcher (`tests/test_slot_choice.py`, with property tests over the real calendar and Ana's own slot sentences), follow-up flags, the booking conditions and the calendar rule (`tests/test_booking.py`), the calendar contract (`tests/test_calendar_contract.py`), `tests/test_scenarios.py` (every `evals/cases/scenarios/S*.yaml` replayed through `evals.runner.run_fake`) and `tests/test_scorers.py` `tests/test_api_tracer.py`, the HTTP boundary, snapshot, end and confirmation endpoints (`tests/test_api_boundary.py`, `test_api_snapshot.py`, `test_api_end.py`, `test_api_confirmations.py`) and the outside-in acceptance test of
the whole tracer bullet through the HTTP boundary. `tests/support.py` builds the app with fakes.
`tests/test_infra_settings.py` checks that every hosted plain setting in `infra/app/main.tf` is
a key of `.env.example`, so a misspelled one cannot be silently ignored.

Fakes live next to the port they implement (`model/fake.py`, `persistence/memory.py`,
`knowledge/fake.py`, `voice/fake.py`); production code never selects them except `main.py`
when the environment asks for them.

`tests/test_known_issues.py` holds strict `xfail` reproductions of `docs/known-issues.md`:
they fail today by design; the commit that fixes an issue removes its marker, and the test
stays as the regression guard.
