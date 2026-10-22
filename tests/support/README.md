# `tests/support`

Shared test code. Test modules import from here and never from each other; the architecture
test (`test_no_test_module_imports_another`) holds the rule.

| Module | Contents |
| --- | --- |
| `__init__.py` | `ROOT`, `CONFIG_DIR` |
| `builders.py` | `NOW`, `SID`/`SESSION`, `CONFIG_ID`/`CONFIG`/`CONFIGS` (loaded once), `EVIDENCE`, `STAMP`, `FULL`, `record(**fields)`, `full_record()`, `session_state(...)` |
| `app.py` | `build_runtime` (the real runtime and handlers over any store), `build_test_app` (the app wired with fakes), `VERSIONS` |
| `harness.py` | `Harness` (runtime + memory store + scripted model), `says`, `name_call`, `turn`, `DATE_CALL`, `present_brief`, `offer_call`, the slot ids, `fill_record`, `with_slots_offered`, `slots_offered`, `SlowFirst` |
| `http.py` | `create_session`, `read_turn` (one turn of SSE), the scripted tracer turns |
| `tools.py` | `context`, `args`: calling a tool handler directly |
| `exports.py` | One session's journal and `snapshot()` for the export tests |
| `evals.py` | The simulated candidate's `PERSONA` and the `record()` of the example export, for the eval tooling's tests |
| `offline.py` | `block_network`, `NetworkBlocked`: the guard every offline test runs under |
| `time.py` | `FakeTime` (one virtual instant for `now` and `sleep`; `advance` wakes what falls due), `settle` |
| `voice.py` | `FakeRuntime`, `Recorder`, `session(...)`: `VoiceSession` without Pipecat, on a `FakeTime` |

Fakes of production ports stay beside their port in `src/` (`model/fake.py`,
`persistence/memory.py`, `knowledge/fake.py`, `voice/fake.py`, `observability/fakes.py`).
