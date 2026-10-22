<p align="center"><img src="docs/assets/logo.svg" alt="Café Norte" width="240"></p>

# Café Norte recruiting agent

**Ana** is a bilingual (Spanish/English) voice and text assistant for a fictional coffee chain.
A candidate can ask about a barista role, give their details in any order, correct them, and
confirm a simulated interview slot. The result is a candidate-confirmed factual brief, a
complete JSON record of the conversation, and evidence of how the system behaved.

This repository is a take-home assessment. Everything in it is fictional: the company, the
stores, the pay, the candidates. No real hiring decision is made or suggested.

## What the demo does today

- **Voice and text on one runtime.** Hosted voice through Daily, Deepgram and ElevenLabs
  (`CAFE_NORTE_VOICE=pipecat`) with barge-in, read-backs that count only once heard, a filler
  while a tool runs and one "¿Sigues ahí?" after silence (D22, D35, D40). Text always works,
  and both channels feed the same `ConversationRuntime`. Voice is hosted or off (D45).
- **Two stores, two languages.** Café Norte Chamberí and Arganzuela, chosen on the page
  (`?store=…&lang=es|en`); Spanish or English for the whole session, switched on an explicit
  request (D28, D38).
- **The candidate record.** Ana opens with the disclosure, collects every field in any order,
  reads back phone and start date, presents a deterministic brief and ends once it is
  confirmed; a plain yes or no to a read-back is taken by the runtime, not left to the model
  (D19, D20, D35).
- **Answers with sources.** Questions about pay, shifts, training, uniform, benefits, the store
  and the interview are answered from twelve fictional documents through `search_knowledge`:
  BM25 plus local multilingual embeddings, filtered by store before ranking, with chunks below
  a measured relevance floor dropped; the page shows title › section › excerpt (D26, D27).
- **Booking.** Interview slots from a simulated seven-day calendar; the candidate's choice is
  matched by the runtime and the confirmed yes is the reservation, one per slot and session
  (D29, D41).
- **Durable sessions.** Memory store locally, Postgres on Cloud SQL when hosted (D31, D33): a
  lease per turn, a private resume link valid seven days, retention purge after seven days,
  delete on request, and the JSON export (`<session_id>.json`) with transcript, brief,
  confirmations, booking, versions and priced cost (D25, D32, D34, D36).
- **Explicit requests and signals.** "Quiero hablar con una persona" is recognised by the
  runtime and flagged for follow-up; an opt-in classifier records frustration (D30).
- **Evidence.** One Langfuse trace per turn with redacted content in the hosted demo, JSON log
  lines, a reviewer panel on the page, and the versions of configuration, prompt, knowledge
  base, schema, model and commit on every session (D36, D42).
- **Hosted** on one Compute Engine VM behind a shared access code, with Cloud SQL through the
  Auth Proxy, all in Terraform (D23, D24, D33), on a free DuckDNS name with the sslip.io name
  as a fallback (D60). The hosted model is `openai/gpt-4.1` (D49).

## What is simulated or still open

- Everything is fictional: the company, both stores, the twelve documents, the pay and the
  candidates. No hiring decision is made.
- The interview calendar is generated, not a real calendar; a booking reaches no one.
- One VM, one shared access code, two voice sessions at a time: a demo, not a service
  ([docs/production.md](docs/production.md) says what breaks first).
- Every issue found in the hosted calls ([docs/known-issues.md](docs/known-issues.md)) is fixed
  offline (KI-01–KI-08, D39–D41, D44); the fixes still need a hosted voice call to confirm.
- The narrative summary is not built: the brief is always the deterministic one.
- No telephony and no native speech-to-speech; both are discussed in `docs/production.md`.
- The evaluation report and the demo video are pending the live evaluation runs.

## Run and test

Install [uv](https://docs.astral.sh/uv/) (it installs Python 3.12 if needed) and Node 24.

```bash
make setup        # locked dependencies, every extra, and the page's npm packages
make check        # ruff, strict mypy, offline tests; tsc, ESLint and Vitest for the page
make test-db      # Postgres-backed tests (starts compose)
make run          # builds the page, http://localhost:8000; reads .env when present
make web-dev      # the page with hot reload on :5173, proxying /api to make run
make evals ARGS="--suite scenarios --mode fake"   # the scripted scenarios CI runs
make voice-smoke  # hosted voice from the laptop (paid; the three voice keys in .env)
```

With no `.env`, the model is a fake that answers every turn with one fixed sentence, the store
is in memory, retrieval is lexical and voice is off: no credentials, no Docker, no network
after installation. To talk to Ana for real, copy `.env.example` to `.env` and set
`CAFE_NORTE_MODEL=openai/gpt-4.1` with `OPENAI_API_KEY` (or
`CAFE_NORTE_MODEL=groq/openai/gpt-oss-120b` with `GROQ_API_KEY`; Groq's free tier caps tokens per
day). For voice add `DAILY_API_KEY`, `DEEPGRAM_API_KEY`, `ELEVENLABS_API_KEY` and
`ELEVENLABS_VOICE_ID` and run `make voice-smoke`, then press **Hablar**. Set
`CAFE_NORTE_DATABASE_URL` for Postgres and the `LANGFUSE_*` keys for traces. Deployment:
[infra/README.md](infra/README.md); operations: [docs/runbook.md](docs/runbook.md).

## How it is built

```text
Browser (React)  ──SSE/POST──▶ api ──▶ conversation runtime ──▶ model (OpenAI | Groq | fake)
Browser ──Daily audio──▶ voice (Pipecat shell) ─┘        │   ├──▶ knowledge (hybrid | lexical)
                                                         │   ├──▶ persistence (Postgres | memory)
                                                         └──▶ domain (pure rules)
```

- **One runtime, two channels.** Voice and text feed the same `ConversationRuntime`; Pipecat
  only moves audio and speech.
- **The model proposes, the domain decides.** Every tool call is validated by pure functions
  before it can touch state. A field is a sum type; `unknown` cannot carry a value.
- **Postgres is the truth.** Nothing is announced before it is committed. Leases, admission,
  slot reservations and idempotency keys are rows with constraints.
- **Evidence over claims.** Every session and evaluation run carries configuration, KB, prompt,
  schema, model and commit versions.

Module map and import rules: [src/cafe_norte/README.md](src/cafe_norte/README.md).
Every directory has its own README.

## Documents

| Document | Contents |
| --- | --- |
| [docs/SPEC.md](docs/SPEC.md) | The specification, with the amendments decided during scaffolding |
| [docs/DECISIONS.md](docs/DECISIONS.md) | Every architectural decision, the options considered and the trade-off taken |
| [docs/architecture.md](docs/architecture.md) | Contracts, turn execution, event protocol, limits, who sees what |
| [docs/evaluation.md](docs/evaluation.md) | Evaluation design: suites, scorers, judge, tracing, what runs where |
| [docs/runbook.md](docs/runbook.md) | Restart, cleanup, failed calls, teardown |
| [docs/known-issues.md](docs/known-issues.md) | Problems seen in real calls: evidence, cause, reproduction, fix and status |
| [docs/production.md](docs/production.md) | Production discussion (spec §17): what breaks first and the next step for calls, replicas, availability, imports, monitoring, privacy, Twilio and speech-to-speech |
| [evals/README.md](evals/README.md) | Running the evaluation suites |
| [infra/README.md](infra/README.md) | Google Cloud deployment with Terraform |

## Delivery checklist

Hosted demo link, access instructions and the demo video are shared separately from this
public repository. See the definition of done in [docs/SPEC.md §18](docs/SPEC.md).
