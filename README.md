# Café Norte recruiting agent

**Ana** is a bilingual (Spanish/English) voice and text assistant for a fictional coffee chain.
A candidate can ask about a barista role, give their details in any order, correct them, and
confirm a simulated interview slot. The result is a candidate-confirmed factual brief, a
complete JSON record of the conversation, and evidence of how the system behaved.

This repository is a take-home assessment. Everything in it is fictional: the company, the
stores, the pay, the candidates. No real hiring decision is made or suggested.

> **Status: tracer bullet** ([D18](docs/DECISIONS.md)). One text turn runs end to end:
> browser, API, runtime, the `update_candidate` tool, domain validation, in-memory store,
> SSE back to the page. Ana opens with the disclosure and collects the whole candidate record
> in Spanish (D19), reads back phone and date, presents the brief, and ends the session once
> it is confirmed (D20). Voice is the browser's own speech recognition and synthesis on the
> same path, or hosted voice through Daily, Deepgram and ElevenLabs with `CAFE_NORTE_VOICE=pipecat`
> (D22), locally and on one Compute Engine VM behind a shared access code (D23, D24). Booking, knowledge and
> Postgres keep their contracts and raise `NotImplementedError`.

## Run and test

Install [uv](https://docs.astral.sh/uv/); it installs Python 3.12 if needed.

```bash
make setup      # locked dependencies, every extra
make check      # ruff, strict mypy, offline tests
make test-db    # Postgres-backed tests (starts compose)
make run        # http://localhost:8000 with fakes; GROQ_API_KEY + CAFE_NORTE_MODEL in .env for a real model
```

With no `.env`, the model is a fake that answers every turn with one fixed sentence, the store
is in memory, retrieval is canned and hosted voice is off: no credentials, no Docker, no network
after installation. Copy `.env.example` to `.env` and set `CAFE_NORTE_MODEL=groq/openai/gpt-oss-120b`
with `GROQ_API_KEY` to talk to Ana for real (or `CAFE_NORTE_MODEL=openai/gpt-4o-mini` with `OPENAI_API_KEY`;
Groq's free tier caps at 200k tokens a day); press **Hablar** in Chrome, Edge or Safari to use
the browser's speech recognition and synthesis.

## How it is built

```text
Browser (vanilla JS) ──SSE/POST──▶ api ──▶ conversation runtime ──▶ model (Groq | fake)
Browser ──Daily audio──▶ voice (Pipecat shell) ─┘        │   ├──▶ knowledge (hybrid | fake)
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
| [docs/production.md](docs/production.md) | Scaling, replicas, telephony and speech-to-speech discussion |
| [evals/README.md](evals/README.md) | Running the evaluation suites |
| [infra/README.md](infra/README.md) | Google Cloud deployment with Terraform |

## Delivery checklist

Hosted demo link, access instructions and the demo video are shared separately from this
public repository. See the definition of done in [docs/SPEC.md §18](docs/SPEC.md).
