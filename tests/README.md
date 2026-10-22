# Tests

`make check` runs Ruff, strict mypy and the offline suite: no network, no Postgres, no
credentials. `make test-db` runs the `postgres`-marked tests against the compose database; CI
runs both. `live`-marked tests are paid and manual (`evals/`).

## The pyramid (D50)

| Folder | Holds | Rule | `make` |
| --- | --- | --- | --- |
| `unit/` | Pure code: domain, signals, slot choice, brief, read-backs, codecs, delivery, cost, scorers; static checks of the repository (import rules, settings, schema) | Imports no store, runtime, handler, app, composition root, adapter or the support built on them (`test_unit_tests_import_only_pure_code`) | `test-unit` |
| `component/` | One module behind fakes: the runtime (`runtime/`, one file per behaviour), the handlers (`handlers/`), the store contract on both stores, the voice session, adapters against scripted transports, the composition root, the eval tooling | Fakes for every port; Postgres only under `@pytest.mark.postgres` | `test-component` |
| `http/` | The app through `build_test_app` and `TestClient`: validation, ownership, SSE, cookies, export, voice routes, the eval HTTP drivers | Fakes behind the app | `test-http` |
| `e2e/` | Whole sessions: `S01`–`S20` replayed through `evals.runner.run_fake` (the deterministic release gate), the tracer-bullet acceptance test, S01 and S12 on Postgres | The real runtime and handlers | `test-e2e` |

`tests/support/` holds the shared builders, the runtime harness, the HTTP, handler and voice
helpers and the Hypothesis strategies (its README lists them). A test module never imports
another test module (`test_no_test_module_imports_another`). Fakes of production ports live
beside their port in `src/` (`model/fake.py`, `persistence/memory.py`, `knowledge/fake.py`,
`voice/fake.py`, `observability/fakes.py`); production code never selects them except
`main.py` when the environment asks for them.

## How a test is written

- **Pure first.** A pure function gets examples and, where a law exists, a property (round
  trip, idempotence, absorption, invariant). Anything with I/O is tested through its port with
  the first-class fake; an adapter is tested by contract, so the same suite runs on the fake
  and the real thing (`store` fixture in `conftest.py`).
- **The name is the behaviour.** `test_a_terminal_session_absorbs_every_event`, not
  `test_transition_3`. The body is given, when, then, separated by blank lines.
- **Assert what can be observed.** Returned values, reads through the `Store` contract, HTTP
  responses, events parsed as models. Not private attributes, not substrings of JSON; a call
  count only when the count is the behaviour (a retry budget).
- **Red, then green.** A new behaviour or a fix starts with a test seen failing. A refactor of
  tests keeps the collected test names identical.

## Notable suites

`component/test_readback_matrix.py` is the read-back behaviour matrix (D39): every kind of
read-back (date, phone, brief, slot) x where its saying is cut x the first reply (yes, no,
correction, carry on, unrelated) x how the candidate goes on, driven by a small policy model
that follows the prompt's rules from the session facts. Every row must settle without a failed
turn, end in the export `assurance` its path predicts, and never say a read-back whole more
than twice. `Harness(model=…)` takes such a model.

`component/test_known_issues.py` holds strict `xfail` reproductions of `docs/known-issues.md`:
they fail today by design; the commit that fixes an issue removes its marker, and the test
stays as the regression guard.

`component/test_store_contract.py` and `component/test_calendar_contract.py` are the store
contract (transactions, conditional save, input ids, the event stream and sequence, the slot
race, idempotent reservation, the snapshot, leases and fenced writes, admission, resume tokens,
export snapshots, expiry and cascading delete, the maintenance lock) on the memory store in
`make check` and on Postgres in `make test-db`.

`unit/test_infra_settings.py` checks that every hosted plain setting in `infra/app/main.tf` is
a key of `.env.example`, so a misspelled one cannot be silently ignored.
