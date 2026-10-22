# `tests/component`

One module behind fakes. `runtime/` is the turn loop with the scripted `FakeModel`, the memory
store and the real handlers, one file per behaviour; `handlers/` calls tool handlers directly
on a `World` (no model, no runtime). Beside them: the store and calendar contracts (memory
here, Postgres under `@pytest.mark.postgres`), the voice session with a fake runtime, Pipecat
processors with frames in memory, adapters against scripted transports, the composition root
and the eval tooling.
