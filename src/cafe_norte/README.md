# `cafe_norte` package

Eight modules, one composition root. Each module exposes its types and ports in `contracts.py`
and keeps adapters private. `tests/test_architecture.py` enforces the import rules below.

| Module | Owns | May import (internal) |
| --- | --- | --- |
| `errors.py` | Languages, error codes, public messages, `ServiceError` | nothing |
| `domain/` | Candidate fields and their transitions, confirmations, booking rules, lifecycle, configurations. Pure: no I/O, no clock, no model | `errors` |
| `model/` | `Model` port, provider-neutral messages and stream events; Groq and fake adapters | `errors` |
| `knowledge/` | Documents, chunks, versioned index, `Retriever` port; hybrid and fake adapters | `domain.contracts` |
| `observability/` | Structured events, usage, prices, cost estimates, version stamps, tracing | `domain.contracts` |
| `persistence/` | Repository ports, Postgres adapter, SQL migrations, JSON export, in-memory fakes | `domain`, `observability.contracts` |
| `conversation/` | `ConversationRuntime`: turn loop, prompt assembly, tool registry, bounded rounds | `domain`, contracts of `model`, `knowledge`, `persistence`, `observability` |
| `voice/` | Pipecat bridge processor, Daily rooms, STT/TTS wiring, voice timings | `domain.contracts`, contracts of `conversation`, `observability` |
| `api/` | FastAPI routes, access and resume cookies, SSE events, health | `domain`, contracts of `conversation`, `persistence`, `voice`, `observability` |
| `main.py` | Reads the environment, selects adapters, builds the app | everything |

Rules of thumb:

- A module imports another module's `contracts.py`, never its adapters. `main.py` is the only
  place that names a concrete adapter. One named exception: `api` imports
  `persistence/export.py`, the published export document and its pure builder.
- `domain/` is the only module whose functions are total and pure; everything the model proposes
  passes through it before it can touch state.
- Public text lives in `errors.py` and `conversation/prompts/`; nothing else formats a sentence
  for a candidate.
- Every record that leaves the process (API, export, trace) is a frozen Pydantic model declared
  in a `contracts.py`.
