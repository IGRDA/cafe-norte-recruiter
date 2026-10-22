<p align="center"><img src="docs/assets/logo.svg" alt="Café Norte" width="240"></p>

# Café Norte

Ana is a voice and text recruiting assistant for a fictional coffee chain. She collects a
candidate's details, answers questions from a store-specific knowledge base, reads back the
facts for confirmation, and books a simulated interview. No hiring decision is made.

Spanish and English have reviewed texts and evaluation cases. Eight more languages are wired
through the same runtime, with model-translated templates; their conversation quality is not
evaluated. The calendar and company information are fictional. The export is a factual record,
with a deterministic brief, transcript, sources, confirmations, usage and version stamps.

## Run

Requires Python 3.12 (installed by uv if needed), [uv](https://docs.astral.sh/uv/), Node 24,
and Docker for the Postgres tests.

```sh
make setup        # locked Python and browser dependencies
make check        # Ruff, strict mypy, offline Python tests, TypeScript, ESLint, Vitest
make test-db      # shared store contracts and integration tests on Postgres
make run          # builds the page and serves http://localhost:8000
make web-dev      # Vite on :5173, proxying /api to :8000
```

Without `.env`, the app uses a fake model, memory storage, lexical retrieval and no voice.
For real conversations, copy [.env.example](.env.example) to `.env`, select
`CAFE_NORTE_MODEL=openai/gpt-4.1` and set `OPENAI_API_KEY`. Set `CAFE_NORTE_DATABASE_URL`
for persistence. Hosted voice needs the Daily, Deepgram and ElevenLabs settings in that file;
`make voice-smoke` starts the server with voice enabled. Provider calls are paid.

## Where to start

[main.py](src/cafe_norte/main.py) composes the adapters. Each module's `contracts.py` defines
its public values and ports; operation docstrings describe effects, ordering and failures.

| Module | Owns |
| --- | --- |
| [domain](src/cafe_norte/domain/contracts.py) | Candidate values, confirmations, booking and lifecycle rules; time is an input |
| [conversation](src/cafe_norte/conversation/contracts.py) | One bounded turn loop for text and voice; persistence precedes announcements |
| [model](src/cafe_norte/model/contracts.py) | Provider-neutral completions and probability-based decisions |
| [knowledge](src/cafe_norte/knowledge/contracts.py) | Store-filtered retrieval over the documents in `kb/` |
| [persistence](src/cafe_norte/persistence/contracts.py) | Transactions, ownership leases, reservations, event replay and exports |
| [voice](src/cafe_norte/voice/contracts.py) | Rooms, audio delivery and call lifecycle; Pipecat carries speech |
| [observability](src/cafe_norte/observability/contracts.py) | Versioned usage, EUR costs, structured events and traces |
| [api](src/cafe_norte/api/contracts.py) | Validated HTTP messages, session ownership and SSE envelopes |

The browser's [reducer](web/src/page/reducer.ts) owns page state; its effect runner owns I/O.
`make export-schema` generates the browser schema and TypeScript from Python declarations.
The export schema is available from `ExportDocument.model_json_schema()`.
[Import checks](tests/unit/test_architecture.py) enforce dependency direction and keep adapters
out of the domain. Tests cover pure rules, components, HTTP boundaries and whole sessions;
shared helpers live in `tests/support/`. `make quality` reports coverage and mutation results.

## Evaluate

```sh
make evals ARGS="--suite scenarios --mode fake"   # same regressions as make check
make evals-retrieval ARGS="--retriever lexical --ragas"
make evals ARGS="--suite scorecard --retriever lexical"
make compare                                    # estimate before paid model comparisons
make evals-signals ARGS="--systems regex"        # free signal baseline
uv run python -m evals.run --help
```

Scenarios share cases and invariants between fake and live runs. Retrieval, signal calibration,
model comparisons and the combined scorecard measure different promises. Paid commands require
`--yes`; use `--base-url` to evaluate an existing server. Scorecard targets live in
[scorecard.py](evals/scorecard.py), case formats in [contracts.py](evals/contracts.py).
Selected baselines in `evals/results/` stay tracked. New output is ignored; promote a reviewed
baseline explicitly with `git add -f <report>`.
`--rescore <recorded-folder>` and retrieval's `--replay <recorded-folder>` reuse paid evidence.

Before merging, run `make preflight` (offline checks, Postgres and selected live regressions),
then `make preview` for the owner's voice call on Postgres with the real providers.

## Hosting

One Compute Engine VM runs the app, Caddy and the Cloud SQL Auth Proxy. Daily's native WebRTC
transport needs a routable network interface, which the tested Cloud Run deployment did not
provide. Text uses POST plus SSE: idempotent input identifiers and sequence-based replay fit
ordinary HTTP and cookie authentication without a bidirectional socket.

The demo has a shared access code, two concurrent voice places by default, seven-day session
retention and no high-availability deployment. See [infrastructure operations](infra/OPERATIONS.md)
for bootstrap, deployment, recovery, secrets and teardown. `docs/` contains visual assets only.
