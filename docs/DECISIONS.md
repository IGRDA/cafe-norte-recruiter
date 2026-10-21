# Decision log

Decisions taken on 20 October 2026 while designing the repository scaffold, with the options
considered and the trade-off accepted. Later decisions are appended with their date. A decision
here is the baseline for the rest of the work; changing one is a new entry, not a silent edit.

Format: context, options, decision, consequences we accept.

---

## D01 · Our runtime owns the LLM loop; Pipecat is the voice shell

**Context.** Every turn runs the same loop (assemble prompt, stream model, validate and run
tools, bounded rounds, stream answer). Voice (Pipecat) and text both need it.

**Options.**
- A. `ConversationRuntime` is ours: a `Model` port, a typed `ToolRegistry`, the domain. Pipecat
  does Daily transport, VAD, STT and TTS; one `FrameProcessor` bridges finalized transcripts in
  and sentences out. The text channel calls the runtime directly.
- B. Pipecat owns it: `GroqLLMService`, its context aggregators and `register_function`; the
  text channel is a second Pipecat pipeline without STT/TTS.

**Decision.** A.

**Why.** The brief grades conversation flow, error handling, testing and design. A puts all of
that in code we own and can test offline with a fake model in milliseconds, keeps one path for
both channels, and ports the luzia model adapter unchanged. B gives tested interruption and
function streaming for free but moves the bounded tool loop and "validate before execute" into
framework callbacks, couples the core to Pipecat's context API, and makes loop tests depend on
the pipeline harness.

**Consequences.** We own streaming tool-call parsing and cancellation; the bridge must honor
Pipecat interruption frames and report what was delivered. The voice adapter is kept thin so a
switch to Pipecat's LLM service for voice only would touch one package if the hosted barge-in
checkpoint demands it.

## D02 · Vanilla ES modules, no frontend build

**Options.** Vanilla ES modules served statically; React + TypeScript + Vite (spec); Jinja + HTMX.

**Decision.** Vanilla ES modules with vendored, pinned `daily-js`.

**Why.** One toolchain, one Docker stage, no Node job in CI, Python stays the main language.
The UI is bigger than luzia's chat page (brief, confirmation cards, reviewer panel) but still a
few renderers over one state object. HTMX fights live SSE state and voice status.

**Consequences.** Hand-rolled DOM rendering; no TypeScript. JSDoc plus `tsc --checkJs` can be
added later without a build step. Amends spec §1 (Browser) and §15 (`web/`).

## D03 · psycopg 3 and numbered SQL migrations

**Options.** psycopg 3 + SQL files + a small migrate command; SQLAlchemy Core + Alembic (spec);
SQLAlchemy ORM + Alembic.

**Decision.** psycopg 3 async pool, forward-only `.sql` files applied under an advisory lock.

**Why.** The spec's hard requirements (ownership leases with generations, admission rows,
row-locked slot reservation, idempotency keys, conditional updates on revision) are SQL-shaped;
an ORM puts a layer between the invariant and the statement that enforces it. Two fewer
dependencies.

**Consequences.** No autogenerate; the schema outline lives in `0001_initial.sql` comments
until it is written. Reviewers looking for `alembic/` will find `persistence/migrations/` and
this entry. Amends spec §1 (Application row) and §8.

## D04 · Package layout: spec modules plus `model/` and `errors.py`

**Options.** Spec layout verbatim (seven modules, model adapters inside `conversation/`);
the same plus a separate `model/` package and a central `errors.py`, with `contracts.py` per
module and an architecture test.

**Decision.** The variant. `src/cafe_norte/README.md` is the import-rule table;
`tests/test_architecture.py` enforces it from the source.

**Why.** D01 needs the runtime to depend on a `Model` port, not on Groq. Stable public error
codes and messages in one place keep internal detail out of candidate-facing text. The
pattern is proven in the reference repository.

## D05 · Langfuse Cloud (EU) for production tracing and evaluation datasets

**Options.** Langfuse Cloud EU; Arize Phoenix (self-hosted); LangSmith; local-only OTel.

**Decision.** Langfuse. OpenTelemetry export from Cloud Run (metadata by default), datasets
and experiment runs for local evaluations, rubric judges configured on the platform.

**Why.** One platform for both halves, EU hosting, free tier covers the demo, OTLP endpoint
already integrated in the reference telemetry module. Phoenix would need its own hosted
service for production traces; LangSmith is US-hosted and LangChain-centred.

**Consequences.** An external account; traces leave the project. Content export is opt-in and
redacted. Self-hosting through compose remains possible.

## D06 · Evaluation stack: own typed runner, ragas for retrieval, Langfuse judge

**Options (multi-select).** Own runner (always); ragas; Langfuse judge evaluators; deepeval;
promptfoo.

**Decision.** Own runner + ragas + Langfuse judge. deepeval and promptfoo declined.

**Why.** The spec's acceptance criteria are deterministic and belong in pure scorers over the
export document. ragas adds standard retrieval metrics on the 24-question set at low cost. The
judge is a secondary signal. deepeval overlaps with the judge; promptfoo is Node-based and
duplicates the runner.

**Consequences.** `evals/` is ours to maintain; framework results are reported next to our
checks, never instead of them. See `docs/evaluation.md`.

## D07 · Auto-deploy on push to `main`

**Options.** Manual `workflow_dispatch` with environment approval (recommended for the €100
ceiling); auto-deploy on push to `main`; laptop-only deploy.

**Decision.** Auto-deploy on push to `main`, with `paths-ignore` for Markdown and `docs/`, a
non-cancelling concurrency group so runs never overlap, and a GitHub Environment (`demo`) that
can be given a required reviewer later without changing the workflow.

**Why.** Chosen by the owner for a tight feedback loop during the one-week build.

**Consequences.** Every merge runs Terraform apply and replaces the Cloud Run revision during
the demo window; deployment drains must be respected (spec §11 operational limits). The
teardown script stays separate and manual. The recommendation to add a manual gate is on
record if spend becomes a concern.

## D08 · Sanitised specification committed as `docs/SPEC.md`

**Options.** Sanitised copy; keep private; commit as is.

**Decision.** Commit a copy with the sentences that reference confidential interview material
removed, plus an amendments table. The original stays git-ignored.

**Why.** Reviewers need the requirements; the spec itself says to keep interview material out.

## D09 · Pydantic v2 frozen models and Protocols

**Options.** Pydantic frozen models everywhere; frozen dataclasses with Pydantic at the edges.

**Decision.** Pydantic everywhere a record exists (`model_config = frozen, extra="forbid"`),
`Protocol` for ports, `Literal` unions for enums, a tiny dataclass `Result` for domain refusals.

**Why.** One mechanism for validation, immutability and JSON Schema; the export schema and the
tool schemas are generated from the same models that the runtime uses, so nothing is written
twice.

**Consequences.** Pydantic in the domain. Accepted: it adds no I/O and the mypy plugin keeps
typing strict.

## D10 · Candidate fields as a discriminated union

**Options.** `Unset | Captured[T] | Confirmed[T] | Unknown | Declined`; a flat
`value: T | None` + `status` record with validators.

**Decision.** The union. Only `Captured` and `Confirmed` carry a value and evidence.
Transitions are total pure functions with property tests.

**Why.** "Never fill unknown or declined with a guess" becomes a type error instead of a
runtime check. The flat export shape is the serialisation of the union.

## D11 · SSE events plus POST per turn for the text channel

**Options.** SSE + POST; WebSocket (spec).

**Decision.** `GET /api/sessions/{id}/events` (SSE, `id: <seq>`, `Last-Event-ID` replay) and
`POST /api/sessions/{id}/turns` with `input_id` and optional `expected_revision`.

**Why.** Reconnect and replay come with the protocol, the POST maps exactly onto "acknowledged
once or safely resubmitted", and cookie authentication is the same as every other endpoint.
We do not use Pipecat's browser client, so bidirectionality buys nothing.

**Consequences.** Heartbeat comments keep Cloud Run's 600 s timeout from idling the stream.
Amends spec §10 (`WS` row).

## D12 · Prompts are versioned files in the repository

**Options.** Repo files with `PROMPT_VERSION`; Langfuse prompt management; both.

**Decision.** Repo files. `PROMPT_VERSION` is recorded on every session and evaluation run.

**Why.** Reproducible from a commit SHA, works offline, one source of truth. Pushing prompts to
Langfuse for visibility can be added as a script later without changing the runtime.

## D13 · First commit depth: contracts and fakes' signatures

**Decision.** Types, ports and function signatures with docstrings; fake adapters declared;
READMEs per directory; two real tests (architecture rules, field-algebra properties) plus the
generated export and tool schemas. Deep modules follow stage by stage.

## D14 · Scenarios: scripted turns in CI, simulated candidate live

**Options.** Both; scripted only; simulator only.

**Decision.** Both. Scripted turn lists against the fake model are the deterministic gate; an
LLM candidate simulator with a persona fixture drives paid live runs and adapts to question
order, corrections, frustration and language switches.

## D15 · Lock every dependency now, behind extras

**Decision.** `voice` (Pipecat + Daily, Deepgram, ElevenLabs, Silero) and `knowledge`
(FastEmbed, rank-bm25) are optional extras; `ragas` and `langfuse` are dev-only. One
`uv.lock` from day one.

**Consequences.** Heavier first `make setup`; no lockfile churn later. Nothing outside
`voice/` and `knowledge/` imports an optional package, and the architecture test forbids it.

## D16 · Postgres-backed tests skip unless a test database URL is set

**Decision.** `make check` stays offline; `make test-db` starts compose and runs the
`postgres`-marked tests; CI runs both with a service container.

## D17 · Cloud Run connects to Cloud SQL through the built-in Unix socket

**Context.** The spec names the Cloud SQL Python Connector, which supports pg8000 and asyncpg
but not psycopg (D03).

**Decision.** Mount the instance on the Cloud Run service (`/cloudsql/<connection name>`) and
let psycopg connect to the socket; credentials from Secret Manager; no public authorized
networks, no VPC connector.

**Why.** It is the documented Cloud Run path, needs no extra library, and keeps D03. Amends
spec §11.

## D18 · Tracer bullet first: one turn end to end, browser speech as a stand-in for voice

_Added 20 October 2026._

**Context.** With the contracts in place (D13), the next commit could deepen one module or
cut the thinnest path through all of them. The brief rewards a working conversation early and
the design wants complexity added in layers.

**Options.**
- A. A tracer bullet: one text turn through API, runtime, one tool (`update_candidate`, one
  field), domain validation, in-memory persistence and the SSE stream, with the browser's own
  Web Speech API (recognition in, synthesis out) feeding the same path for voice. Tests offline
  with `FakeModel` and `MemoryStore`; the Groq adapter ships so `make run` with a key is real.
- B. Module by module: finish the domain, then persistence on Postgres, then the runtime.
- C. The full voice stack (Pipecat, Daily, Deepgram, ElevenLabs) in the first slice.

**Decision.** A.

**Why.** Every layer is exercised once, so the next layers extend code that already runs; the
integration risk with a real model is met in the second pull request instead of the sixth; CI
never needs a credential. Web Speech costs about eighty lines of JavaScript that `voice/`
replaces without touching `app.js`, and it gives a usable voice loop today. C puts three
provider accounts in front of the first conversation; B defers the first conversation by weeks.

**Consequences we accept, and what is deliberately missing.**
- Only `update_candidate` is registered; the registry advertises registered tools only.
- Spanish only in the prompt; `language` is carried and `en` is refused nowhere yet.
- No access code, resume tokens, snapshot endpoint, cancellation, repair budget, signals,
  leases, Postgres or tracing. Each stays `NotImplementedError` behind its port.
- Sequence numbers live in the runtime per process; Postgres will own them.
- Ana does not open the conversation; the candidate greets first. The opening turn is part
  of the lifecycle stage.
- Browser speech has no barge-in and no meaningful latency figures; nothing from it is a
  measurement.

## D19 · Ana opens with fixed text; the model resolves dates and marks unknown or declined

_Added 20 October 2026, with the full-record stage._

**Decisions.**
- The opening is the spec §2 sentence from `prompts/opening.md`, journaled at session creation
  as an ordinary turn (`input_id="opening"`), with no model call. The disclosure is therefore
  word for word and free; voice will play the same sentence on join.
- Relative dates are resolved by the model from `today` (Europe/Madrid) and the weekday given
  in the session facts; the domain refuses past dates and the read-back is the safety net. A
  Spanish date parser is not written unless evaluations show the model getting it wrong.
- `unknown` after two failed clarifications and `declined` on refusal are the model's calls,
  made through the patch's `unknown` and `declined` sets; the server records the attempt count
  and the evidence. Counting questions per field on the server would need the runtime to parse
  what each sentence asked, which is more machinery than the rule is worth at this stage.
- A self-reported `work_authorization` of `no` or `unsure` appends a review flag in the same
  save as the patch and never blocks anything (spec §3).

**Consequences.** Confirmations, the brief and the ending land in the next pull request; until
then Ana closes the collection with a sentence and the session stays `active`. D18's "Ana does
not open the conversation" no longer holds.

## D20 · Read-backs are spoken by the runtime, word for word; the session ends by tool

_Added 20 October 2026, with the confirmation stage._

**Decisions.**
- Phone and date are read back right after capture; the brief is presented when every requested
  field is settled. The text comes from `conversation/brief.py` filling `prompts/brief.md`
  (4 to 8 short sentences; unknown and declined stay visible; the optional phone only when
  given). The runtime speaks it verbatim through `ToolOutcome.spoken` and stores the same text
  as the pending confirmation, so shown, spoken and confirmed are one string. The model is told
  it was already said and adds nothing. The domain keeps no candidate-facing text, so brief
  rendering lives in `conversation/`, not `domain/candidate.py` as the scaffold planned.
- A bare yes or no resolves only the pending confirmation, through `confirm_field` or
  `confirm_brief` and `domain.confirmation.respond`; affirm needs it pending, delivered and at
  the current revision. For the text channel "delivered" is set when the sentence is journaled;
  voice will set it on playback acknowledgement.
- Interview intent is recorded as a note until the booking stage; the session ends through
  `end_session` and `lifecycle.transition` (`completed / brief_only`, or `stopped /
  not_interested`). A turn on an ended session fails with the new `session_ended` code.
- Work-permit `no` keeps the spec's rule: a review flag, nothing blocked, nothing ended.
- Coverage floor `fail_under = 80` over the whole package; raised as stubs fill.

## D21 · Scenarios are data and the gate lives in `make check`

_Added 20 October 2026._

**Decisions.**
- A scenario is one YAML file: the candidate's lines, the fake model's script (`fake_script`,
  one list of `{tool, args}` / `{say}` steps per line) and the checks. `tests/test_scenarios.py`
  replays every file through the real runtime with `FakeModel` and `MemoryStore`, so the gate
  is part of `make check` and the CI `check` job; `make evals --mode fake` is the same replay
  printed for humans. Zero tokens, under a second per scenario.
- Checks run over the final `SessionState`, the transcript and what Ana said per turn
  (`SessionResult`). `build_export` stays a stub: it needs a confirmation history, a version
  stamp and a brief the persistence layer may not render. The checks keep their names so they
  move to the export document unchanged when it lands.
- `max_repeated_questions` ignores the system's own read-back questions, which repeat by
  design when a brief is presented again after a correction.
- Live mode, the judge and the simulator stay manual and arrive with the evaluation stage.

## D22 · Hosted voice: VoiceSession owns the logic, Pipecat carries audio, tests never pay

_Added 20 October 2026, with the voice stage (local half)._

**Decisions.**
- Paid services are I/O at the edges. `voice/session.py` (`VoiceSession`) holds every voice
  decision (turns, the delivery ledger, interruption, opening, filler, silence) as plain Python
  tested with a fake runtime and a recorder; `voice/delivery.py` is pure. Two tiny
  `FrameProcessor`s in `voice/bridge.py` map frames to session methods and are tested with
  Pipecat's in-memory `run_test`. `voice/pipeline.py` only assembles services. CI never
  opens a provider connection; one manual live smoke per PR does.
- Pipecat 1.13's `LLMUserAggregator` is used for what it does well: Silero VAD, the VAD start
  strategy (which interrupts the bot), the speech-timeout stop strategy that waits for a
  transcript, and joining Deepgram's segments. It emits the finished user message; the bridge
  turns it into one runtime turn and keeps Pipecat's context empty. No Pipecat LLM, no
  smart-turn model: D01 holds. Reason: `UserStoppedSpeakingFrame` is a system frame that skips
  processor queues, so joining segments in our own processor would race.
- Delivered means heard: a sentence counts once its `TTSStoppedFrame` has passed the output
  transport; on an interruption the runtime learns exactly which sentences were heard, and a
  read-back is `fully_delivered` only when its last sentence was. The text channel still
  marks on journaling.
- `CAFE_NORTE_VOICE = off | browser | pipecat`. `browser` (Web Speech, D18) stays until the
  hosted exchange is verified and is removed in the deploy PR.
- Cost guards from day one: two voice sessions per container, the session cap plus a
  two-minute margin as room expiry with ejection, 8 s silence prompt then pause, Daily rooms
  destroyed on stop. The hosted checkpoint runs on the memory store with one instance.



## D23 · First hosted deploy: two Terraform stacks, access code, memory store, OpenAI in the cloud

_Added 21 October 2026._

**Decisions.**
- `infra/bootstrap` (state bucket, GitHub Workload Identity pool and provider restricted to
  `IGRDA/cafe-norte-recruiter` on `main`, deployer service account, the billing budget) is
  applied once by a person with Application Default Credentials. `infra/app` (Artifact
  Registry, runtime service account, secret names, Cloud Run v2) is applied by CI on every
  push to `main` with the image digest it just built (D07). The budget sits in bootstrap because
  the CI deployer has no billing-account permissions and must not need them.
- The hosted page is public; the app's shared access code (`POST /api/access`, HttpOnly cookie
  that is a signature of the code) gates session creation. The code and the cookie secret are
  Secret Manager versions written by `scripts/set_secrets.py`, never by Terraform.
- The hosted model is `openai/gpt-4o-mini`: Groq's free tier (8k tokens/min, 200k/day) cannot
  serve a shared URL. The Groq selector stays for the model comparison.
- The checkpoint runs on the memory store with one always-on instance (min = max = 1): a
  restart loses sessions, which the Postgres stage fixes behind the same `Store` port. Cloud
  SQL and the uptime check are not provisioned (`enable_database = false`).
- The smoke check after a deploy makes no model call: page, health, access gate, session
  creation. Deploys cost nothing and cannot fail on a provider hiccup.
- Service-level scaling defaults filled by the Cloud Run API are ignored in Terraform; the
  template scaling is what we set.

**Measured on the first deploy.** Bot joins a Daily room from the container in 2.9 s;
`POST /voice` end to end 200 in 2.9 s; smoke green; both plans empty after apply.

## Assumptions recorded without a question

- Python 3.12, `uv`, Makefile targets, Ruff and strict mypy, as in the reference repository.
- Code and documentation in English; candidate-facing text in Spanish (Spain) and English.
- Store configurations are YAML validated into `StoreConfiguration` at startup.
- The knowledge index is built during the Docker image build, not committed.
- Summary jobs run in-process from a Postgres job table; no Cloud Tasks.
- The default judge and simulator model is configured per run; using the answering model as
  judge is labelled as a bias in reports.
- One initial commit for the scaffold.
