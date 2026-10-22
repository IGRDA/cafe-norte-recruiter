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
  (English and the switch arrived with D28.)
- No access code, resume tokens, snapshot endpoint, cancellation, repair budget, signals,
  leases, Postgres or tracing. Each stays `NotImplementedError` behind its port.
- Sequence numbers live in the runtime per process; Postgres will own them.
- Ana does not open the conversation; the candidate greets first. The opening turn is part
  of the lifecycle stage.
- Browser speech has no barge-in and no meaningful latency figures; nothing from it is a
  measurement. (Removed by D45.)

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
  hosted exchange is verified and is removed in the deploy PR. (Removed by D45.)
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

## D24 · Hosted demo on one Compute Engine VM, not Cloud Run

_Added 21 October 2026. Overturns the hosting half of D23 and spec §11; spec §11 already named
Compute Engine as the fallback "if the early checkpoint shows Cloud Run cannot sustain it"._

**What the checkpoint showed.** Every hosted voice attempt (Firefox and Chrome, with and without
a VPN, and a synthetic `daily-python` candidate playing a PCM file) ended the same way: the bot
joins the Daily room, Deepgram and ElevenLabs connect, TTS audio is generated, and no media
flows in either direction; "¿Sigues ahí?" after the 8 s silence. Daily's session logs show the
bot's send and receive transports stuck in ICE `checking` while laptop clients reach
`connected`. Cause: a Cloud Run container's only IPv4 address is link-local (`169.254.8.1` on
`ipvlan-eth0`), which libwebrtc excludes from candidate gathering, so daily-core never offers
an ICE candidate. UDP egress itself works (STUN binding to four public servers answered).
Direct VPC egress plus Cloud NAT gives the container `169.254.9.1`: same result. `daily-python`
exposes `iceServers` and `placement` but not `iceTransportPolicy`, so a relay-only (TURN)
workaround is not available from the SDK.

**Options weighed.**

| Option | Cost (standing) | Voice media | Why not / why |
| --- | --- | --- | --- |
| Cloud Run, always-on instance (D23) | ≈ 45 EUR/month | No: no ICE candidates (above) | Rejected by evidence |
| Cloud Run + Direct VPC egress + Cloud NAT | ≈ 45 + NAT ≈ 35 EUR/month | No: still a link-local address | Tried, rejected |
| Cloud Run with a TURN-only ICE policy | ≈ 45 EUR/month + TURN | Unknown: the SDK cannot set the policy | Not reachable without forking daily-core |
| GKE Autopilot or a Cloud Run sidecar proxying media | > 70 EUR/month, days of work | Probably | Disproportionate for a two-session demo |
| **One e2-small VM, Container-Optimized OS, Docker, Caddy for TLS** | **≈ 15 EUR/month + static IP** | **Yes: a routable NIC** | **Chosen** |

**Decisions.**
- `infra/app` provisions a static regional address, an ingress rule for 80/443, and one
  `e2-small` Container-Optimized OS instance running two containers with host networking:
  the app image by digest and `caddy:2.9` as a reverse proxy with automatic HTTPS on the free
  `sslip.io` name derived from the address (`https://<ip-with-dashes>.sslip.io`). No domain to
  register for a three-week demo; the URL changes only if the address does.
- The instance's startup script (`infra/app/startup.sh`) is the whole deploy: it reads the
  image reference and plain settings from instance metadata, fetches secret versions from
  Secret Manager with the runtime service account (`latest`, as on Cloud Run), writes a
  root-only env file, pulls the image and starts both containers. Secrets still never pass
  through Terraform.
- A deploy is Terraform apply with the new digest (metadata changes in place) followed by
  `gcloud compute instances reset`, which re-runs the startup script. The reset is a step in
  `deploy.yml`, not a provisioner, so Terraform stays declarative and a by-hand deploy is two
  commands. Downtime per deploy is the boot plus image pull, about a minute; sessions are in
  memory and are lost either way until the Postgres stage.
- The runtime service account gains `roles/artifactregistry.reader` (image pull) and keeps
  secret accessor and log writer; the deployer swaps `roles/run.admin` for
  `roles/compute.admin`. Nothing else in bootstrap changes.
- What we give up versus Cloud Run: managed TLS (Caddy does it), zero-downtime revisions,
  automatic OS patching (COS auto-updates, the container does not), and request-level
  autoscaling, which the two-session cap never needed. What we gain: voice works, and the
  standing cost drops to roughly a third.
- Cloud SQL, when it arrives, connects over the VM's public address with the Cloud SQL Auth
  Proxy as a third container or the Python connector; D17's Unix socket note applies to Cloud
  Run only and is superseded.

**Measured on the VM (synthetic `daily-python` candidate, 2026-10-21).** `POST /voice` 200 in
3.5 s; the bot gathers a host candidate on the VM's NIC and a server-reflexive one on the
static address, DTLS completes in under 2 s; the candidate's 7 s of speech triggers VAD, the
bot stops its opening (barge-in) and answers through ElevenLabs; smoke green; both plans empty
after apply. Two Container-Optimized OS facts cost a boot each: `/root` is read-only (docker
login needs a writable `HOME`) and the host firewall drops inbound except ssh (the startup
script opens 80/443). The browser exchange with an interruption is recorded in the PR.

## D25 · The export is built on demand from one snapshot; history comes from the journal

_Added 21 October 2026, with the export stage._

**Decisions.**
- `Store.snapshot(session_id, versions, taken_at)` is one consistent read; `build_export` is a
  pure function over it. `GET /api/sessions/{id}/export` builds the document on request for the
  session owner, at any lifecycle. `Exports.write_snapshot` (a stored JSONB copy at session
  close) waits for the Postgres stage; on demand already covers "regenerate after a correction".
- The confirmation history and the session's end time are derived from the journaled
  `state_updated` events (last status per confirmation id, the first terminal lifecycle). No
  domain record changed; Postgres keeps the same events table. `SessionState.created_at` is
  set once by the route that creates the session.
- The deterministic brief is the text of the confirmed brief read-back; `narrative_status` is
  `skipped` and the cost estimate `None` until the summary job and prices exist.
- `api` may import `persistence/export.py`: the document is a published record, not an adapter.
- `examples/session_export.example.json` is S01 replayed offline (`make export-example`). Turn
  and confirmation ids are random, so the test checks content, not bytes.

**Why.** The export is the deliverable the spec names first; building it from what the store
already journals ships it without a confirmations table, a summary worker or Postgres, and
every piece moves unchanged when those land.

## D26 · Knowledge: the model reformulates, the handler filters, one small hybrid index

_Added 21 October 2026, with the RAG stage._

**Decisions.**
- `search_knowledge(question, query, topic)`. The semantic half of the query is the model's:
  one self-contained Spanish `query` (an English question is reformulated there, which is also
  how English retrieval works). The structured half is the handler's: configuration, KB
  version and `topic → documents` (`faq` always allowed) are applied before ranking. No second
  model call for query rewriting; the tool result lets the model search once more in the same
  turn, bounded by the four tool rounds.
- Hybrid from day one: own thirty-line BM25 (no `rank-bm25`) plus dense cosine, fused by
  reciprocal rank among the allowed chunks only. `Embedder` is a port: FastEmbed in the
  `knowledge` extra, `FakeEmbedder` (hashed bag of tokens) in tests, so `make check` never
  downloads a model. Chunk = one `## ` section, at most 90 words (the embedding model's 128
  tokens).
- Two modes: `lexical` builds BM25 over `kb/` at startup (local default, no extra);
  `hybrid` loads the artifact `kb/index/<kb_version>/` built by `make build-index` and in the
  image, and warms the model before serving.
- Abstention is the prompt's job plus the `unknown_policy` document. The retriever always
  returns its top three; the 24-question suite reports what unsupported questions get back.
  A relevance floor, multi-query fusion and `request_human_followup` are the next stage, chosen
  from those numbers.
- The export's `retrieval_events` carry `sources_found`, not `answered`: whether a snippet
  answered is a judgement, not a fact the system holds.
- After the confirmed brief Ana invites questions before asking about the interview; the
  opening says questions are welcome.

**Measured (2026-10-21, local, `paraphrase-multilingual-MiniLM-L12-v2`).** recall@3 16/16
answerable, 0/24 leaked, every unsupported question returned three chunks (no floor), median
6 ms per retrieval after warm-up. BM25 alone finds every Spanish answerable question.

## D27 · Relevance floor from measured scores; phrasings fused; follow-up as a flag

_Added 21 October 2026, the second RAG pull request._

**What the numbers said.** Fused RRF scores are rank-based: the top chunk of a supported and
of an unsupported question both score ≈ 0.032, so no floor can live there. On raw scores
(`evals/results/retrieval/`), the best cosine of answerable questions ran 0.41–0.78 and of
unsupported ones 0.30–0.45: a cosine-only floor would cut the two weakest answerable questions
before the strongest unsupported one. What separated cleanly: every answerable chunk that had
no lexical match scored ≥ 0.40, and the unsupported questions with no lexical match scored
≤ 0.37.

**Decisions.**
- Floor: a chunk no query word occurs in is kept only when its cosine is ≥ 0.40
  (`DENSE_FLOOR`). Lexical overlap is evidence and survives any floor. Result: recall@3 stays
  16/16, two of four unsupported questions return nothing; the other two (semantically close
  to a real section, e.g. the manager's salary next to the barista's) stay the prompt's job.
  The constant is re-measured whenever the embedding model or the KB changes; the manifest
  records both.
- Multi-query: `RetrievalQuery.queries` holds one to three phrasings; each gets a BM25 and a
  dense ranking (one batched embed call), all fused by RRF; a chunk's raw scores are its best
  across phrasings. The model adds a second Spanish phrasing for vague or English questions.
- `request_human_followup(reason)` appends one `ReviewFlag(kind="human_followup")` and the
  conversation continues; the tool text and the prompt offer it when nothing answers, and the
  candidate is told nobody real is notified. No outcome change: `human_followup_requested`
  as a session outcome waits for the signals stage, where an explicit "quiero hablar con una
  persona" gets its synchronous path.

**Not done.** ragas and Langfuse sync (not chosen), and a floor that uses the second-best
chunk's margin (no evidence it would help on 24 questions).

## D28 · English is a session fact; an explicit request switches it before the model runs

_Added 21 October 2026, the language stage._

**Context.** `Language` was carried everywhere but every candidate-facing sentence was
Spanish, and `explicit_controls` was a stub. The spec wants either starting language, an
explicit switch that applies to the current turn, and retained state.

**Decisions.**
- `SessionState.language` is the one current language. `CandidateRecord.preferred_language`
  is removed: a preference, not a collected fact, and a second copy to keep in sync. Each
  `TurnRecord.language` keeps the language of its own turn.
- The switch is a pure pattern match (`signals.explicit_controls`) on the finalized text: a
  language name with a request word around it ("in English", "en inglés", "English, please",
  "en castellano"). A borrowed word or a mention ("I studied English") never matches. Exactly
  one requested language switches; none or both leave it alone. No model tool.
- The runtime applies it at the start of the turn and saves it in the same transaction as the
  user turn, so the record, `TurnStarted.language`, the prompt and the reply all agree. The
  model answers that turn in the new language; there is no fixed acknowledgement.
- Instructions stay one Spanish `system.md` with an "Idioma" section: reply only in
  `language`, never change it yourself, queries to the knowledge base stay Spanish (D26).
  The system message ends with `language.<lang>.md`, one line written in the session
  language. Measured live: without it, gpt-4o-mini answered an English session in Spanish
  from the first turn; with it, every turn stayed English, and the switch turn was English
  from its first sentence.
- Text the system speaks word for word has one file per language, `<name>.<lang>.md`
  (`brief`, `opening`, `voice`, `language`), with identical keys held by a test. Language-specific layout
  is a template row (`date`), so `brief.py` has no Spanish logic.
- Voice: the session's language is passed when voice starts; `VoiceSession` follows each
  `TurnStarted.language` for the filler and idle prompt. Deepgram runs `multi`; ElevenLabs
  takes the language from the text. Browser speech follows the turn the same way.
- The page takes the opening language from `?lang=`; the picker reloads into a new session.
- Scenario ids follow the spec: the old S02 (correction after the brief) is S04; S02 is the
  English happy path in Arganzuela; S07 is the switch from Spanish to English.

**Consequences we accept.**
- No implicit switch: a candidate who simply writes in English without asking keeps getting
  Spanish until they ask. Live S07 runs show whether the pattern list needs more phrasings.
- A read-back pending at the moment of a switch stays pending and in the language it was
  read in; a yes or no in either language answers it.
- Postgres rows written before this change still carry `preferred_language` and no longer
  validate; the demo runs on the memory store (D24), so only local test data is affected.

## D29 · Booking on the memory store: generated slots, intent by tool, the yes is the reservation

_Added 21 October 2026._

**Context.** The first line of the definition of done (bookings need an explicit matching
confirmation and survive duplicates) on the in-memory store, before Postgres. The five
conditions of SPEC §9 were already written in `domain/booking.py`'s docstring.

**Decisions.**
- Slots are a rule, not a fixture: each store configuration names its `interview_times`
  ("10:30", "17:00"); `domain/calendar.py` yields one 30-minute slot per time on each of the
  next seven local days that has a shift, with deterministic ids
  (`<config_id>-<YYYY-MM-DD>-<HHMM>`). Seeding at startup and in the scenario runner is
  therefore idempotent, and a scenario with a fixed `today` always sees the same ids. A YAML
  calendar would go stale and need a date-shifting trick in every test.
- Explicit intent to schedule is a fact with evidence on the session, never a candidate
  field: a patch bumps the revision and would void the brief confirmation the booking needs.
  `list_interview_slots(evidence_text)` saves the candidate's words as
  `SessionState.schedule_intent` in the same write that offers the slots.
- `brief_confirmed_revision` on the session records the brief the candidate affirmed.
  Presenting a slot replaces `pending_confirmation`, so "brief confirmed at the current
  revision" can no longer be read from it; the handlers and the `brief_confirmed` scorer read
  the field.
- `reserve_interview(slot_id)` is the candidate's yes to the pending slot read-back and the
  commit: the domain resolves the confirmation (`respond(affirm)`, so the same-turn and
  not-delivered refusals apply), `reservation_allowed` checks the five conditions, and the
  calendar row and the session are saved in one transaction. No `confirm_slot`: the allowlist
  keeps its nine names and SPEC §4's "slot ID and matching confirmation". Another choice is
  `present_confirmation` with the other slot, which supersedes the pending one.
- The runtime speaks the slot offer and the slot read-back verbatim (D20), in Madrid local
  time; the model only names slot ids, in the order they were offered.
- The memory calendar enforces one booking per slot and per session and returns the original
  booking for a known idempotency key, checked at enlist and again at commit.

**Deferred.** Postgres row locks and S14/S15 across containers (persistence stage); automated
rescheduling (a change request is a `request_human_followup` flag, per SPEC §9). The slot
sentences took a language when D28 and D29 were merged.

## D30 · Explicit requests are patterns in the runtime; frustration is an opt-in classifier

_Added 21 October 2026, the signals stage (frustration bonus, S09)._

**Decisions.**
- `explicit_controls(text)` is pure: anchored phrases for `human` and `stop` in both
  languages, matched per clause after lowercasing and removing accents; a negation in the three
  words before a match cancels it, so "no quiero hablar con una persona" is not a request and
  "para" as a preposition is not a stop. The same call returns the language requests of D28;
  it takes no language, so a request for a person in the other language still counts, and the
  runtime reads the controls once, before it resolves the turn's language.
- A human request is handled by the runtime before the model: `add_followup` saves a
  `human_followup` flag (one per turn; the tool handler uses the same function), `StateUpdated`
  is emitted, then the fixed reply in `prompts/controls.<lang>.md` is said word for word: nobody can be
  reached now, the interview will be with a person, the request is noted, the demo notifies
  nobody real, the candidate may leave at any time. The conversation continues; the model runs
  for any fact in the same sentence but voices nothing more.
- A stop request is a hint (`explicit_requests` in the session facts); the model still calls
  `end_session(candidate_stop)` and says goodbye. No second ending path in the runtime.
- Outcome: an early end (`stop`, `abandon`, `fail`) with any `human_followup` flag is
  `human_followup_requested`; withdrawn interest still wins as `not_interested`; `complete`
  keeps `reserved`/`brief_only` with the flag beside it. The brief states the request in one
  fixed sentence.
- The classifier is opt-in (`CAFE_NORTE_SIGNAL_MODEL`), so the default setup and CI pay
  nothing. It runs after `TurnFinished` in a background task, through the same `Model` port; a
  verdict without verbatim evidence, late (5 s) or malformed is no signal. Verdicts are
  journaled as `SignalRecorded` (the export's `signals` come from the journal;
  `Events.record_signal` is removed) and the latest is kept in memory. Only a `frustrated` or
  `uncertain` verdict from the immediately previous user turn reaches the prompt
  (`candidate_sentiment`); the prompt then shortens the question and offers to skip a
  nonessential field or ask for a person. Never a hiring input.

**Not done.** Persisting the latest signal across resume (it is soft and per-turn); a
frustration lexicon without a model.

## Assumptions recorded without a question

- Python 3.12, `uv`, Makefile targets, Ruff and strict mypy, as in the reference repository.
- Code and documentation in English; candidate-facing text in Spanish (Spain) and English.
- Store configurations are YAML validated into `StoreConfiguration` at startup.
- The knowledge index is built during the Docker image build, not committed.
- Summary jobs run in-process from a Postgres job table; no Cloud Tasks.
- The default judge and simulator model is configured per run; using the answering model as
  judge is labelled as a bias in reports.
- One initial commit for the scaffold.

## D31 · Postgres adapter: a polling stream, migrations at startup, the store owns the sequence

_Added 21 October 2026, the first of four persistence pull requests._

**Context.** The demo ran on the memory store (D23, D24). The definition of done needs restart
survival, private resume and booking races decided by the database. The owner split the stage
into four pull requests: this adapter for what the app uses today; leases, admission rows and
resume tokens; Cloud SQL in Terraform with the Auth Proxy on the VM; export snapshots and
retention.

**Decisions.**
- One JSONB document per session (`sessions.state_json`, the `SessionState` as Pydantic writes
  it) with the columns the database must see generated from it (`revision`, `lifecycle`,
  `outcome`, `language`, `config_id`, `config_version`), so a column can never disagree with the
  document and a new field needs no migration. Normalised candidate tables were rejected: the
  field sum type (D10) would become a status column plus a nullable value, two codecs to keep in
  sync and a migration per field.
- A slot is taken exactly when a `bookings` row names it; `interview_slots` has no status column.
  `bookings.slot_id UNIQUE` and `bookings.session_id PRIMARY KEY` are the invariants; `reserve()`
  locks the slot row `FOR UPDATE`, returns the original booking for a known idempotency key,
  refuses a taken slot, and lets the primary key refuse a second booking for the session. A
  concurrent reserver waits on the lock and sees the winner. Bookings do not cascade from a
  deleted session on purpose: it must fail loudly until the retention stage decides.
- Confirmations keep no table: the history is derived from the journaled `state_updated` events
  with the pure function D25 introduced. The spec's `confirmations` table is amended out.
- Event payloads are JSONB, usage and timings typed tables; every child table cascades from
  `sessions`; ids are `text`, times `timestamptz`, read back as aware UTC.
- The store owns the event sequence: `Sessions.next_seq` is `UPDATE … SET next_seq = next_seq + 1
  … RETURNING`, called inside the journaling transaction. The runtime's per-process counter is
  gone, so a restarted container continues where the store stopped; PR2 adds the lease
  generation as a second condition on the same statement. A session that does not exist is no
  longer journaled against: there is no row to sequence and nobody can stream it.
- `Events.since` polls every 200 ms (500 events per poll). LISTEN/NOTIFY was weighed: a
  dedicated listening connection per container competes with a pool of five, needs reconnect
  logic, and still needs a poll for missed notifications; at two voice sessions the poll costs
  one indexed primary-key range read. It is the documented upgrade when streams per container
  grow past a few dozen.
- Migrations are applied by `PostgresStore.open()` under one advisory lock, with `make migrate`
  as the by-hand path. One path for compose, the VM and tests; a bad migration stops the app at
  boot, which is the intended failure. The spec's "CI runs it before switching traffic" is
  amended; the runtime role needs DDL until Cloud SQL splits roles.
- `make run` keeps the memory store unless `CAFE_NORTE_DATABASE_URL` is set, so the fake-mode run
  needs no Docker. Hosted voice on Postgres is refused at startup until the admission rows exist
  (PR2): a per-process cap a restart forgets is worse than no cap.
- Tests: the memory store's tests became one contract suite over both stores through a
  parametrized `store` fixture (memory in `make check`, Postgres in `make test-db`, each test on
  truncated tables); the record/row codecs are pure and property-tested offline; database
  timeouts surface as `timeout` and pool exhaustion as `busy`; one end-to-end test replays S01 on
  Postgres and lets a second process continue the session.

**Consequences we accept.** JSONB normalises payload text (nothing compares it byte for byte)
and rejects `\u0000`; a poller can read event N+1 before N commits when two writers journal at
once (the lease serialises them in PR2); the hosted demo stays on the memory store until the
infrastructure stage.

## D32 · One lease per turn fences every write; the resume link is the credential

_Added 21 October 2026, the second persistence pull request (leases, admission rows, resume)._

**Decisions.**
- A lease is one row per session (`owner`, `generation`, `expires_at`). The runtime claims it
  after the per-session lock for every turn, the opening and the resume, with a 60 s TTL, hands
  the generation to every `save` and `next_seq` of that turn (the tool context carries it to
  the handlers) and releases it at the end. `release` expires the row instead of deleting it, so
  generations only grow and a writer fenced on an old one can never pass again. Another owner's
  live lease fails the turn with `conflict` before anything is written. No renewal loop: a turn
  is bounded well under the TTL, and a crashed container blocks its session for at most a
  minute. `delivered()` and `end()` stay unfenced: both are idempotent. A per-session lease was
  rejected because it needs the renewal loop on day one and blocks a session for the whole cap
  after a crash.
- Voice admission is a row per admitted session, counted under a table lock, and a row older
  than 600 s (the session cap plus a margin) no longer counts, so a container that dies without
  releasing frees its place by itself. Euros are recorded for the cost report and not enforced:
  a spend ceiling waits for the price table and stays a documented control, as the spec allows.
- The resume link: a 256-bit token issued at session creation, only its hash stored, the token
  in the URL fragment, exchanged by `POST /api/resume` for the session cookie, reusable until it
  expires seven days later (spec §8). The page shows it once and in the reviewer panel; nothing
  is mailed. A single-use token was rejected: a bookmarked first link would confuse, for little
  gain against a leaked link that expires anyway.
- `resume_session` is a system turn like the opening: `paused` becomes `active` through the
  lifecycle table, Ana says `prompts/resume.<lang>.md` and repeats a pending read-back so a yes or
  no still has a target; no model call; a reservation is restated, never rebooked. The page
  rebuilds the transcript from the replayed journal, so no snapshot endpoint was added.
- S12 and S13 are not scripted conversations: they are an end-to-end test on Postgres (restart,
  zombie lease, resume) and API tests with fakes (wrong, expired, guessed).

**Consequences we accept.** A resumed voice call gets a new room on the next **Hablar**; the
hosted demo keeps the memory store until Cloud SQL (next pull request), so resume links there
survive only while the process does.

## D33 · Cloud SQL entirely in Terraform; a write-only password; the Auth Proxy on the VM

_Added 21 October 2026, the third persistence pull request._

**Context.** PR1 and PR2 made the app durable on any Postgres; the hosted VM still ran the
memory store. Spec §11 names Cloud SQL; D24 moved the app to a VM, so D17's Unix socket no
longer applies. The owner's rule: the database is infrastructure as code too, nothing by hand.

**Decisions.**
- `infra/app/database.tf`: Postgres 16 on `db-f1-micro`, 10 GB HDD, zonal, public address with
  no authorized networks, daily backups with three kept, no point-in-time recovery, no deletion
  protection (the demo is torn down by script). The database, the user, the IAM binding, the
  secret and the connection name as instance metadata are all Terraform; `enable_database` is
  now true by default and keeps the memory-store path for a demo without a database.
- The VM reaches the instance through the Cloud SQL Auth Proxy as a third container with host
  networking, authenticated by the runtime service account (`roles/cloudsql.client`). The app
  sees `postgresql://…@127.0.0.1:5432/cafe_norte`, built by `startup.sh`, which waits for the
  proxy's port before starting the app. Private IP was weighed and rejected: private services
  access and a peering for a three-week demo buy nothing the IAM-authenticated proxy does not.
- Authentication is one built-in user whose password is an ephemeral `random_password` passed
  only through write-only arguments: `google_sql_user.password_wo` and
  `google_secret_manager_secret_version.secret_data_wo`, both keyed to `db_password_version`.
  The password is never in the plan or the state (D23 keeps holding), the VM reads it at boot
  like every other secret, and a bump of one variable rotates it everywhere. This needs
  Terraform 1.11 or later: CI moved from the pinned 1.5.7 to `~1.12`, and the laptop needs
  `hashicorp/tap/terraform` (Homebrew's `terraform` formula is frozen at 1.5.7). IAM database
  authentication was rejected because Cloud SQL Postgres 16 gives a new IAM user no CREATE on
  schema `public`, which would need one GRANT by hand per fresh database. A password in state
  was rejected by D23.
- One user for the demo: it owns the schema, applies the migrations at startup (D31) and serves
  the app. The spec's separate migration role is amended for the demo window.
- The deployer service account gains `roles/cloudsql.admin` in the bootstrap stack, which a
  person applies once (D23); the first deploy after that creates the instance (about ten
  minutes, inside the job's thirty).

**Consequences we accept.** About 8 EUR a month more standing cost, inside the Google Cloud
allowance for the demo window. A reset of the VM during an instance creation would fail the
readiness wait; the next deploy recovers. Backups keep deleted rows for up to three days.

## D34 · The export is stored at close; retention purges under one lock; delete takes everything

_Added 21 October 2026, the fourth and last persistence pull request._

**Decisions.**
- When a session reaches a terminal state, from a tool or from `end()`, the runtime runs a close
  hook after the state is committed and announced; the hook (`persist_export`) builds the export
  from one snapshot and stores it (`exports` table, one row per session, upsert). The export
  endpoint serves the stored document for a closed session and still builds on demand while the
  session is open, so a correction before the close needs no regeneration step. The narrative
  summary stays `skipped`: the deterministic brief is the deliverable and the model-written
  summary is optional in the spec.
- Retention: sessions created more than `CAFE_NORTE_RETENTION_DAYS` (7) days ago are deleted at
  startup and every hour, at most 100 per round, only by the container holding the store's
  maintenance lock (a Postgres advisory lock on a dedicated connection; a flag in memory).
  Deleting a session cascades to its turns, events, usage, timings, lease, admission rows, resume
  token, export and simulated reservation; the slot is free again. Schema `0003` adds the
  exports table and the cascade on bookings, which PR1 had left strict on purpose.
- `DELETE /api/sessions/{id}` is the owner's delete action from the page, idempotent; a running
  voice session is stopped first.

**Consequences we accept.** Deleted rows remain in Cloud SQL backups for up to three days (D33);
provider-side retention stays the providers'. A session whose close hook fails keeps serving
its export on demand, and the failure is logged.

## D35 · The hosted voice call of 21 October: the flow stops depending on the model's obedience

_Added 21 October 2026, after a hosted voice interview on gpt-4o-mini (session `f5f84f57…`)._

**What the journal and the logs showed.** Soft "sí" answers produced no VAD event for 30 s
while Deepgram transcribed them, so five of them waited for a louder phrase; Deepgram `multi`
heard "sí" as "C" and "Sì"; a 0.6 s pause split one question into three turns; the silence
timer paused the session mid-call; the model answered "Sí, es correcto" without
`confirm_field`, and a later patch left the date confirmation unanswerable (stale revision);
it saved 35 hours, the store's contract, from "por la mañana"; an interrupted summary looped
`present → already pending → not delivered` into the round limit twice; one model round took
over six seconds and the turn failed in silence; "¿dónde está el establecimiento?" was never
searched; the silence prompt was heard but never shown.

**Decisions.**
- A plain yes or no to a read-back the candidate fully heard is resolved by the runtime before
  the model (`signals.answer_to_readback`, whole utterance, fillers allowed, both languages),
  through the same registry and domain rules as the model's tool call; the model is told in
  `readback_answered`. Anything more than a plain answer stays the model's.
- A pending field confirmation survives another field's patch at the new revision.
- Hours are saved only when the candidate's words contain the number, as digits or spoken
  (`domain/numbers.py`); the prompt says `store.hours_per_week` is the offer.
- A read-back from an earlier turn that was not fully heard is read again by
  `present_confirmation`; one just said in the same turn is not.
- A silent model round is retried once (spec §12); a second miss fails with `timeout`, and the
  voice channel says a fixed apology instead of going quiet. Round latencies are logged.
- Silence prompts once and never pauses a live call; any raw transcript resets the clock; the
  session pauses when the call ends; a turn on a paused session makes it active.
- Turn start is VAD or a transcript (Pipecat's own default pair); turn end after 1.0 s of
  silence; Deepgram runs in the session language and follows a switch. Smart-turn was not
  added: a new model in the image for a problem the timeout already fixes.
- Everything Ana says goes through the journal: `Runtime.say` for the silence prompt and the
  apology, `Runtime.aside` for the filler.
- The address sections of both stores use the words people ask with (knowledge base version
  2); the prompt sends place questions to `search_knowledge` and forbids "no tengo
  información" without a search.
- The hosted model stays gpt-4o-mini: with the above, its tool slips no longer leave the
  session stuck. Re-tested live after deploy before reconsidering gpt-4o.

**Consequences we accept.** 0.4 s more latency per spoken turn. A Spanish session hears an
English request to switch through the Spanish recogniser until it switches. `S19` replays the
call on the fake model; the voice behaviour is covered by unit tests with Pipecat frames and a
manual `make voice-smoke`.

## D36 · Observability: one trace per turn, our own cost, events as JSON lines

_Added 21 October 2026, after the hosted voice call of D35: reading the `events` journal by hand
from inside the app container was the only way to see what happened._

**Context.** D05 chose Langfuse Cloud (EU) for production tracing and left it unwired.
Every number we quote about a call (cost, latency, which version answered) should be one click
from the session, and the export should carry an honest cost.

**Options.**
- A. Plain OpenTelemetry with `langfuse.*` attributes, on a private provider.
- B. The Langfuse Python SDK in `src/`.
- C. OTel calls directly inside the runtime, or a `Telemetry` port the runtime holds.

**Decisions.**
- **A, behind a port.** `Telemetry` and `Span` live in `observability/contracts.py`; the runtime
  holds the port, `main.py` picks the adapter. No Langfuse SDK in `src/` (it stays an
  evaluation dependency, D06), no global tracer. Parents are passed explicitly
  (`span.child(...)`) because a turn is an async generator and ambient context does not survive
  its `yield`.
- **Off without keys.** With both `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` the adapter
  exports to `LANGFUSE_BASE_URL` (EU by default); without them nothing is traced and events
  still go to stdout. `make check` needs neither, and tests use an in-memory exporter.
- **One trace per candidate turn**, named by its root, with stable span names; the round,
  attempt and retry are metadata, never part of a name:

  ```
  handle-candidate-turn            root · outcome, tools_called, rounds, chars_in, chars_out
  ├─ write-user-turn               the store transaction
  ├─ invoke-agent        [agent]   the round loop
  │  ├─ step             [chain]   one model round (round = n)
  │  │  ├─ chat          [generation]  model, tokens, EUR cost, time to first token
  │  │  ├─ search_knowledge [retriever]
  │  │  └─ update_candidate [tool]     ok, arguments and result as content
  │  └─ step
  │     └─ chat
  └─ write-assistant-turn
  ```

  A silent round that is retried is one `chat` with `silent_attempts: 1`. A failed span is
  `ERROR` with its code; a turn on an ended session is a failed root with no children.
- **Every span carries the trace attributes**, because Langfuse filters per observation:
  session, release (`commit_sha`), environment (`CAFE_NORTE_ENVIRONMENT`, default
  `development`), tags (channel, language, store) and the whole `VersionStamp` as filterable
  metadata. `langfuse.version` is the `prompt_version`. No user id is sent: candidates are
  anonymous and the session is the unit.
- **Our euros, not Langfuse's.** A generation sends `usage_details` and `cost_details` from the
  same price table the export uses, so the two agree. Langfuse labels totals in dollars; the
  numbers are euros (`cost_currency: EUR` is in the metadata). A model with no price sends
  tokens and no cost: a missing number beats a wrong one.
- **Prices are a data file** (`observability/prices/v1.yaml`: USD, the page each came from,
  converted at the ECB rate of 21 October 2026, 1.1234 USD/EUR). Cached input tokens are priced
  as full input, Deepgram at its list price (the page shows a limited-time lower one), Daily at
  the audio-only first tier without the free minutes: all conservative. Token usage is keyed
  by the configured model id, not the dated snapshot id the provider echoes.
- **The export prices its usage.** `build_export` takes an `Estimator`. A voice call's speech,
  listening and room minutes are not measured anywhere, so they are derived from the snapshot
  (characters Ana spoke, `active_seconds`, twice that in participant minutes) and marked
  `estimated`. `cost_is_partial` is true when any usage has no price, when any is estimated,
  or when no estimator is bound.
- **Content is opt-in.** Only `CAFE_NORTE_TRACE_CONTENT=on` exports it: the turn's input and
  output, each generation's input (the newest messages it saw, system prompt excluded since
  `prompt_version` pins it) and a tool's arguments and result. Always redacted first
  (emails, phones, DNI/NIE, IBAN, cards, secrets), truncated after.
- **Events replace the ad hoc logs**: `turn_failed`, `model_round` (attempt, first output,
  total), `model_round_silent`, `answer_cut`, as JSON lines keyed by session and turn. A payload
  key named `text`, `transcript`, `content` or `message` is refused.
- **The shutdown flush is bounded** (5 s) and runs in a thread, last in the lifespan.

**Consequences we accept.** A trace is only as good as its flush: a crash loses the last batch
(at most 2 s). Langfuse shows euros as dollars. The hosted app's keys are Secret Manager
versions written with `set_secrets.py --only` and its host and `CAFE_NORTE_ENVIRONMENT=production`
are plain settings of `infra/app` (added 21 October, after the first hosted traces were wanted).
Not yet recorded: the signal analyzer's tokens, a cancelled generation's tokens (no usage
chunk arrives), Pipecat's own STT/TTS metrics. Live evals, datasets and experiments are a
later stage.

## D37 · Runtime robustness: a repair budget, an active-time cap, cancellation that leaves a trace

_Added 21 October 2026, after D35 left several rows of the spec's failure contract (§12) without
code or without a test and the scenario table (§13) without S08, S10, S11, S16, S17 and S18._

**Decisions.**
- **Repair budget.** A tool call is malformed when the tool is unknown or its arguments do not
  validate (`ToolOutcome.malformed`, set by the registry). The first one goes back to the model
  with the validation error and the turn gets one more round; the second ends the turn with
  `invalid_response` (`Limits.max_repairs = 1`). A domain refusal (a past date, a taken slot, a
  confirmation not heard) is not malformed: the model is told and the four-round limit bounds
  it. The fixed sentence loses its jargon: "Perdona, no te he entendido bien. ¿Me lo repites?".
- **Session cap.** `SessionState.active_seconds` grows by what a turn adds: the gap since Ana
  last finished, at most 30 s, plus the turn's own duration (`domain/session_time.py`, pure; time
  is an argument). The gap is capped so a pause, a lost connection or a resume link opened days
  later does not eat the 480 s; the candidate's own speaking and thinking do count, which a
  server-time-only measure would leave out. The sum is written in the transaction that stores
  the assistant turn, so the cap costs no extra round trip. The turn that crosses the cap is
  finished normally and saved; in the same transaction the session becomes `abandoned`, then
  `StateUpdated` is announced and Ana says `controls.<lang>.md` `time_cap`, which is part of the
  stored turn. Refusing the next turn instead was rejected: the candidate's last answer would
  never be processed and they would hear the goodbye only after speaking again. The session's
  remaining seconds were already the model deadline; now they are real.
- **Cancellation.** Closing `run_turn` mid-stream or cancelling the task that reads it closes the
  provider stream, stores what was generated as an interrupted assistant turn (sentences go
  straight into the turn's spoken list, so a partial round is not lost), journals
  `TurnFinished(interrupted=True)`, counts the active time and releases the lease. A failure to
  write while cancelling is logged and the cancellation goes on. `VoiceSession` reads the turn
  under `aclosing`: a barge-in while a sentence is being spoken closes it at once, not whenever
  the generator is collected. Only the model round is closed explicitly; tool handlers hold no
  external stream and are bounded by their own deadline.
- **Scenarios.** A scenario may name `faults` (the candidate speaks over Ana after N sentences,
  the model provider is down for a turn, the store refuses the next save) and
  `seconds_per_turn` (the runtime's clock). The faults live in the fakes (`FakeModel.fail_next`,
  `MemorySessions.fail_next_save`), one-shot, raised where a real failure would be. A turn a
  scenario asserts failed (`turn_failed`) is not a surprise. New scorers: `tool_ok` (every call
  of a tool on a turn answered as asked), `turn_failed`, `brief_unconfirmed`. S18 is the time
  cap; its silence and overload halves stay in `test_silence_prompts_once_and_never_pauses_a_live_call`
  and `test_a_third_concurrent_voice_session_is_busy`, as S12 and S13 stay in their own tests (D32).
- **Bypass attempts (S17).** The fake model plays a model that obeys every instruction in the
  line; the scenario asserts what the runtime and the domain refuse regardless: a booking
  without a heard read-back, a session or configuration argument, a confirmation with nothing
  pending. What a real model says after reading an injected knowledge-base passage is not
  tested offline; the guarantee is that no text can widen the allowlist, the arguments or the
  domain rules.

**Consequences we accept.** A turn that crosses the cap speaks its normal answer first, so the
candidate can hear a question and then the goodbye in the same turn. Turns that fail (timeouts,
a refused save) add no active time, so a session that only fails is not capped by this rule; the
admission row (600 s) and the voice room expiry still bound it. An interruption that arrives
before the user turn is stored leaves no assistant record. The scenarios were each checked by
breaking the rule they guard; S16's first version could not tell a refused save from a swallowed
one (the script ran out and failed the turn either way) and was strengthened.

---

## D38 · The page and API gaps: a chooser in the URL, buttons that answer as a turn, one boundary

_Added 21 October 2026._

**Context.** The spec's browser and API contract (§10) still lacked the store chooser, the
reviewer panel's versions and per-turn detail, the snapshot, the UI confirmation, the end
endpoint and a hardened boundary.

**Decisions.**
- **Chooser.** The page creates nothing until a store is chosen. The choice lives in
  `?store=&lang=`; the chooser reloads into a new session, as the language picker did (D28).
  The header names the store; a resumed session reads its store, language and versions from
  `GET /api/sessions/{id}`.
- **Buttons are a turn with an explicit answer.** `POST …/confirmations/{id}` names the
  read-back pending now (404 otherwise) at the revision the candidate saw (409 if it moved or
  was answered), then runs a turn whose `TurnInput.ui_answer` replaces the parsing of words. The
  runtime resolves it with the tool a spoken answer uses (D35), so the domain refuses what it
  refuses for the model. The card on screen counts as heard: pressing the button marks a
  read-back delivered first. The transcript records the language's label (`ui.<lang>.md`).
  Rejected: sending "sí" as text (language-dependent, ignores the id) and calling the tool in
  the route (Ana would say nothing, and a second path to keep in step).
- **Snapshot and end.** The snapshot is typed (`SessionState`, `TurnRecord`, `VersionStamp`)
  and carries `last_seq`, where the stream resumes. `POST …/end` stops a running call, then ends
  like any stop; ending twice changes nothing. Both check ownership like every session route.
- **Versions** come in the create reply and the snapshot; timings, usage, tool outcomes and
  retrieval excerpts come from the stream the page already follows. The panel shows no hidden
  reasoning.
- **One boundary.** `HttpBoundary` is installed by the app factory, so local and hosted runs
  send the same headers: a CSP with no inline code (Daily is the only third party),
  `Referrer-Policy: no-referrer`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`.
  A body over 64 KiB is refused with 413, declared or streamed. Validation errors carry a fixed
  message and never the input.
  _Amended 22 October 2026:_ `script-src 'self' 'unsafe-eval'`. daily-js fetches its call
  machine from `c.daily.co` and runs it with `Function()`. Under `default-src 'self'` that was
  blocked, and no browser could join a room. The scripted Daily bot that verified hosted voice
  ignores the CSP, so the failure went unnoticed. Inline scripts stay blocked.

**Consequences we accept.** A new conversation is a page load. A button answer to a read-back
the voice has not finished saying counts as read. The browser speech mode (D22) stays until a
follow-up removes it. (Removed by D45.) `ui.<lang>.md` is new candidate-facing text; `PROMPT_VERSION` is unchanged
because the model never sees it.

---

## D39 · A read-back the candidate cut is offered once, gone over in parts, or carried on

_Added 21 October 2026, after the second hosted voice call (KI-01, KI-02). Built in two parts:
the word families, the domain stage and the parts (PR #26); the tool, the router, the prompt,
the export and the matrix (branch `readback-review-2`)._

**Context.** The summary takes about 12 s to say and is shown on the page at once. The
candidate read it and said "Sí, está todo bien" 10.8 s in. D22 counts only what was heard, so
the yes could not confirm it; D35 read it again, word for word; it was cut the same way,
three times, until the turn hit its round limit. "Está todo bien" was not even a plain yes
(KI-01): the phrases had to match whole.

**Decided with the owner (21 October).** Voice only first: the page mirrors the call and
never counts as hearing it. A read-back cut by a yes gets one natural offer to go over it or
carry on, and then the candidate decides. An explicit carry-on confirms it, recorded as
*confirmed without full review*. What is confirmed stays the fixed text (D20); the bridge
around it is the model's, from a short general policy. A long read-back is gone over in short
parts, each one checked. No verbatim re-read loops.

**Decisions.**
- **A yes is a family of words**, in any order, with fillers and at least one core word and no
  negation (`signals.answer_to_readback`). A carry-on ("sigue", "adelante", "no hace falta";
  "carry on", "skip") is a third answer, `skip`. A bare "no" never rides along with a carry-on.
- **The review is domain state.** `Confirmation.review` is `None` (said once, whole), or
  `offered`, `in_parts(part, parts)` or `waived`, each stamped with the turn that moved it: one
  move per turn. `fully_delivered` means the latest saying (the whole text, or the part) was
  heard. `advance_review` holds the table:

  | now | yes | carry on |
  | --- | --- | --- |
  | said, not heard | offered | offered (no carry-on before the offer) |
  | offered | first part | waived |
  | a part that is not the last (heard, or cut by the yes) | next part | waived |
  | the last part, cut | waived | waived |

  A yes over a part answers that part's check, so the review moves on; only a cut last part
  ends it waived. `ready_to_confirm` is true when the read-back was heard whole, its last part
  was heard, or it was waived; `respond` and the booking conditions use it. `assurance` says
  which: `heard`, `reviewed` or `waived`.
- **Parts** are slices of the read-back's own sentences (`readback.review_parts`): at most two
  sentences and 160 characters, without the intro and the closing question, each followed by
  `review.check` ("¿Está bien?" / "Is that right?"). A one-sentence read-back is one part.
- **One tool, `review_readback(answer: affirm | skip)`.** Its handler moves the review and
  saves; it says the part verbatim through the runtime, or asks the model for the offer; on a
  waiver it confirms in the same call through the read-back's own handler (`confirm_field`,
  `confirm_brief`, `reserve_interview`), so a model that stops there leaves nothing pending. A
  read-back that is ready goes straight to that handler. The allowlist has ten tools.
- **The runtime routes a plain answer by the stage** (`readback.answer_call`, one pure table),
  before the model, as D35 does for a heard read-back:

  | read-back | yes | carry on | no |
  | --- | --- | --- | --- |
  | ready to confirm | its tool, yes | its tool, yes | its tool, no |
  | cut, not reviewed | review (the offer) | review (the offer) | its tool, no |
  | offered | review (first part) | review, carry on | review, carry on |
  | in parts | review (next part) | review, carry on | its tool, no |

  A plain "no" to the offer ("¿lo repasamos?") is carrying on. A no to a slot stays the
  model's. The button is routed the same way and no longer marks a read-back delivered:
  **D38's "the card counts as heard" is superseded.**
- **Presented again, a cut read-back starts with its first part** (`start_parts`), once:
  **D35's verbatim re-read is superseded.** Under review, `present_confirmation`, `confirm_*`,
  `reserve_interview` and the next step after a save all point at `review_readback`.
- **The prompt** (`ana_v16`) gets `heard` and `review` in `pending_confirmation` and one short
  policy: offer once, briefly, in your own words, phrased so that a yes means going over it;
  never repeat the read-back; the system says the parts.
- **The export** carries `assurance` on every confirmed read-back, so a reviewer tells a
  heard one from one confirmed without full review.

**Evaluation.** The behaviour matrix (`tests/test_readback_matrix.py`, 180 rows on fakes):
each kind of read-back x where it is cut x yes, no, correction, carry on or unrelated x going
over it or carrying on. In every row nothing is confirmed outside the three assurance paths,
the assurance is the one the path predicts, no read-back is said whole more than twice, and
nothing loops to the round limit. Before the router 106 rows never settled. S21 (carried on)
and S22 (gone over) replay the call. The live, simulator-judged half runs S21 and S22 through
task B's simulated candidate with their `persona` and `rubric`; no second simulator is built
here.

**Rejected.** A short spoken summary with the full one on the page (the page must not be
needed). Counting a read-back as heard once shown on a connected page (voice only first).
Saying a cut part again (a verbatim loop). Leaving "no" at the offer to the model (gpt-4o-mini
has skipped confirmation tools before). A second call from the runtime to confirm after a
waiver (the model would have to make it too, or task C's tool loop would).

**Consequences we accept.** A yes that cuts a part moves on even though that part was not
heard to its end; a cut last part is recorded as waived, never as reviewed. A press of Sí on a
card whose audio was cut earns the offer instead of confirming. The resume sentence still
repeats a pending read-back in full (a third saying across a hang-up). A button answer in a
voice call is not spoken in the call (D38's gap).

---

## D40 · What Ana says is timed by what the candidate can hear

_Added 21 October 2026, after the second hosted voice call (KI-03, KI-04, KI-05)._

**Context.** "¿Sigues ahí?" was said while the candidate was speaking, twice after a failed
turn, and the apology and the prompt were journaled at once and queued behind a summary still
playing. Pipecat's user aggregator consumes every transcript frame, so the D35 transcript hook
behind it never fired; the failure path and the playback acknowledgement each armed the clock;
the apology did not wait for the audio already sent to TTS.

**Decisions.**
- Every sentence Ana says, from the model or fixed (opening, filler, apology, silence prompt),
  goes through one `VoiceSession._voice` into the delivery ledger. The ledger is the audio
  queue: what was sent and what has played.
- A system sentence never jumps that queue. A failed turn's queued sentences play to the end;
  then the turn is acknowledged with what was heard (its summary may be a read-back), the
  apology is journaled and spoken, and only after it has played does Ana listen.
  One place decides this, `_drained`, which runs whenever playback empties and when a turn ends.
- Silence is audible silence: the filler (1.5 s, while a tool runs) and the silence prompt
  (8 s) share `_after_silence`, which counts only once the queue has played and restarts if
  anything is said meanwhile.
- One silence prompt per candidate turn: the allowance resets when the candidate's words become
  a turn, never on a timer or on Ana's own playback. Listening starts in one place, `_drained`,
  and is a status, not a second flag. Speech evidence (the aggregator's interruption, by VAD or
  transcript, and any raw transcript) restarts the countdown; a cough with no turn still gets
  its one prompt later; speech after the prompt does not earn another.
- Raw transcripts are seen by `SpeechTap`, between STT and the aggregator. `user_side` builds
  tap, aggregator and bridge in order for the pipeline and for the test, which runs the real
  aggregator in `run_test`.
- An interruption drops an apology still owed: the candidate is already speaking.

**Rejected.** Cutting the queued audio when a turn fails: the transcript already shows those
sentences, and cut short they count as unheard, which feeds the KI-02 loop. Cancelling the clock
on speech until the next turn: a noise with no transcript would leave Ana silent for good.

**Consequences we accept.** After a failed turn the apology comes later, after the summary, not
when the failure happens. The VAD start itself is only exercised live (`make voice-smoke`); the
offline tests cover the transcript start through the real aggregator and the interruption at
the session.

---

## D41 · The slot choice is matched by the runtime, not copied by the model

_Added 21 October 2026, after KI-06 (the second hosted voice call)._

**Context.** Offered three slots, the candidate said "El viernes.", "El viernes.", "Exacto, sí."
and "El viernes, veintitrés, a las diez y media." gpt-4o-mini had to copy a slot id from the tool
text into `present_confirmation`: it listed again, asked in plain text, reserved with nothing
read back and presented an id that does not exist. Nothing was booked. D35 had already taken the
plain yes and no away from the model; the choice of slot is the same kind of answer.

**Decisions.**
- The offer is state: `SessionState.slot_offer` keeps the slots in the order Ana said them
  (`OfferedSlot`: id and start) and a `shortlist`. `list_interview_slots` writes it in the same
  save as the intent. A later offer keeps the first `schedule_intent` as the evidence.
- `domain/slot_choice.py` is pure and takes no language. `read_slot_words(text)` reads
  positions, weekdays, days of the month, relative days ("esta mañana" is today), clock times and
  a part of the day, and returns the words it did not explain. `choose_slot(words, offered, today,
  shortlist)` returns `Chosen | Ambiguous | NoMatch | NotAChoice`. Each feature said is a filter,
  features intersect, and values of one feature are alternatives. An hour below twelve also
  means the same hour after noon. A shortlist narrows the next answer while it keeps any match.
- Only an answer that is all about the slot is a choice, the rule D35 applies to a plain yes. Every
  word left over must be the talk around a choice ("me va bien", "mejor", "vale", "sí",
  "¿tienes algo…?"). One other word ("no", "ninguno", "otro", "presencial", "dura") leaves the
  answer to the model. That one rule covers refusals and questions: "¿La entrevista dura treinta
  minutos?" is not the 30th, and "¿es presencial el martes?" is not Tuesday's slot.
- The runtime calls the existing tools after `_plain_answer`, through the registry, as D35 does:
  - `Chosen`: `present_confirmation`. If the heard read-back of that same slot is pending, the
    answer is to "¿Te la reservo?": with a plain yes among the words ("Exacto, sí, el viernes a
    las diez y media") it is `reserve_interview`, without one it is the model's.
  - `Ambiguous`: the shortlist is saved and the model is told which slots fit, to ask which one in
    its own words.
  - `NoMatch`: `list_interview_slots` again, for the day named if any.
  - `NotAChoice`: nothing; the words are the model's.

  The model reads what happened in `slot_choice` (prompt `ana_v15`).
- The five conditions of D29 are unchanged: every path goes through the handlers and
  `reservation_allowed`.
- Vocabulary lives in the domain module, with accents removed; numbers come from
  `numbers.spelled`. A property test says every slot back in Ana's own words (`brief.slot_time`)
  in both languages and gets that slot, so the module and the brief tables cannot drift apart.

**Consequences we accept.** A choice said with a word outside the list ("el viernes, que es
cuando libro", "sí, el viernes, no hay problema") goes to the model, as every choice did before
D41: a missed word costs the old path, never a wrong action. The list grows from the journal. Tool arguments are still not in the journal (KI-06's
observability half); the Langfuse span carries them.

---

## D42 · Hosted traces carry redacted content; one line turns it off

_Added 21 October 2026, with the production notes (`docs/production.md`)._

**Context.** D36 made content opt-in and left the hosted app without it. KI-06 showed the cost:
the journal does not record tool arguments, and the trace did not either, so the slot id the
model sent to `present_confirmation` could not be read anywhere. A bug seen only in a hosted call
stayed a guess.

**Decision.** `CAFE_NORTE_TRACE_CONTENT=on` in `plain_env` (`infra/app/main.tf`), decided by the
owner on three terms: the demo's data is fictional, redaction runs before export (D36), and
switching off is one word and a push (`docs/runbook.md`). Rejected: keeping content off (KI-06
stays a guess) and a Terraform variable for it (a second place for the same fact, and the
plain settings beside it are not variables either).

**What is exported.** The turn's input and output, a generation's newest messages within 1 800
characters (the system prompt is not sent: `prompt_version` pins it), and a tool's arguments and
result, each redacted for emails, phones, DNI/NIE, IBAN, cards and secrets, then cut at 2 000
characters (D36, `docs/architecture.md`).

**Tests.** Redaction and what content exports are D36's (`tests/test_telemetry.py`). New:
`tests/test_infra_settings.py` requires every `plain_env` key to be in `.env.example`, because
the app ignores an unknown key and a misspelled switch would leave content off without a sound.
A test pinning the value to `on` was rejected: it would make switching off a two-file change.

**Consequences we accept.** Redaction is pattern-based: a name or an address said in free text is
not a pattern, so this is safe because the data is fictional, not because the filter is complete.
Langfuse keeps what it received under its own retention, not our seven days (D34). With real
applicants it is `off`, and `docs/production.md` §10 lists what must exist first. Spans exported
before the switch is turned off stay in Langfuse until deleted there.

---

## D43 · Live evaluations: the same scorers over HTTP, a simulated candidate that cannot forget, spend only with --yes

_Added 21 October 2026, task B of the parallel branches._

**Context.** Every evaluation beyond the offline replay was a stub (D06, D14, D21). The model
decision for the hosted demo (gpt-4o-mini or gpt-4o), the release gate's live S01 and S02, and
part of D39's evidence all need live runs, and none could be made without hand-driving the
browser.

**Decisions (agreed with the owner).**
- **One fold, two modes.** A turn's `RuntimeEvent`s fold into a `TurnObservation`
  (`evals/observation.py`); the fake replay reads them from the runtime and the live runner from
  the SSE stream, so the scorers never know which mode produced a `SessionResult`.
- **The public API, on loopback by default.** `HttpConversation` drives a session exactly as the
  browser does (access, create, one POST per line, the turn's events resumed by `Last-Event-ID`,
  end, snapshot, export). The comparison serves the real app on `127.0.0.1` with one server per
  model (`serve`), memory store, text only, traces tagged `evaluation`; `--base-url` targets the
  hosted demo or `make run` instead. Rejected: external URL only (the model would be known only
  from the version stamp afterwards).
- **Explicit `live_checks`.** A simulated candidate adapts to Ana and runs on a real clock, so
  live checks name no turn (`sources_shown_on_any_turn`) and dates are relative
  (`next monday`). S01, S02 and the six comparison scenarios carry them; others are refused
  live. Rejected: reusing `checks` and skipping turn-indexed ones (S05 and S06 would lose the
  grounding the comparison must measure).
- **Extraction accuracy from the persona.** Exact-match facts (name, phone, permit, days,
  shifts, hours, start date), corrections applied and declined fields left out, against the
  final record; free text is the judge's. Every miss is named.
- **The simulator decides in code and words with a model.** `cue(persona, language,
  transcript)` is pure: questions on fixed lines, corrections on the first brief read-back,
  the language switch and the withdrawal after a named line. `ModelCandidateSimulator` only
  words the cue, so a run cannot pass because the simulator forgot to correct. One simulator
  model for every run (`openai/gpt-4o-mini` by default), so the candidate is the same for both
  answering models.
- **Spend is explicit.** Every paid command prints an estimate from the export's own price table
  (`evals/spend.py`; assumptions in `docs/architecture.md`) and calls nothing without `--yes`.
  The fake model and the fake simulator run the whole path for free. gpt-4o joins the price
  table.
- **The comparison is spec §13's, with the owner's models.** Six cases × `openai/gpt-4o-mini`
  and `openai/gpt-4o` × two runs: 24 runs, about €5 by the estimate. This amends the spec's
  GPT-OSS pair: the decision now open is the hosted model, and `--models` takes any pair.
- **Reports carry denominators.** Every rate is k/n, every median says its n, a broken run is a
  recorded miss in every denominator, by model, by configuration and language, and by case.
  The comparison's summary and runs (no conversations) are committed under
  `evals/results/comparison/`; exports go to `evals/results/live/`, ignored.
- **The judge is a labelled second opinion.** One JSON boolean per rubric bullet or
  `unparsable`, never coerced and never pass/fail; a judge that is the answering model is
  flagged.
- **ragas by ID.** The retrieval fixture's expected sections are chunk ids, so ragas'
  ID-based context precision and recall apply exactly, offline, with no model (`--ragas`).
  ragas 0.4.3 did not import with langchain-community 0.4; the dev extra pins it below 0.4.
- **Langfuse through a port.** `ExperimentSink` with a fake; the SDK adapter replays recorded
  runs through `run_experiment` (the supported write path in langfuse 5, which deprecated
  dataset run items): checks and metrics as scores, the session id on a span so the experiment
  item sits next to the server's own turn traces. Opt-in with `--langfuse`; nothing is sent
  without keys.

**Tests.** `tests/test_eval_*.py`: the fold, the HTTP adapter against a scripted server built on
the app's own SSE encoder, loopback runs of S03 that get the fake mode's verdicts, the cue
table, the simulator and judge over `FakeModel`, spend, report, comparison plan, ragas, and
Langfuse with a fake sink and a stub client. No test needs a key or the network.

**Consequences we accept.** Latency is measured over HTTP on the runner's clock: it says how the
text path behaves, not the voice path (D40's timings stay the measure there). The estimate is
deliberately high, so the real export cost will usually come in lower. A free-text fact is not
scored exactly. The comparison has not been run: the owner decides when to spend on it, and the
model decision will be its own entry with the committed numbers.

---

## D44 · Fewer wasted rounds, a joined hesitation, the whole cost, tool arguments in the journal

_Added 21 October 2026, for KI-07, KI-08, D36's "not yet recorded" and KI-06's observability
half. Options were chosen by the owner before building._

**Context.** In the second hosted call the model re-sent saves that changed nothing
(`unchanged`, seq 39, 47, 49, 60) and answered a read-back in the turn that said it
(`same_turn`, 62). Each round costs 0.6–0.9 s, and those turns took 2.1–3.4 s to the first
sentence. The repeats came before Ana spoke, so ending the loop alone would have left her
silent. A pause split "El lunes, … dos de noviembre" into two turns, and the second cancelled
the first before anything was said (KI-07). The export's cost left out the classifier's tokens
and every cancelled generation, and it derived a call's speech usage from the snapshot, so
every voice cost was partial. The journal did not record tool arguments, so KI-06's slot id
could not be read without Langfuse.

**Decisions.**
- **An idle call is a type.** `ToolOutcome.idle` is set where the outcome is built: on a save
  that only repeats known values, and on the `same_turn` refusals of `confirm_field`,
  `confirm_brief` and `reserve_interview`. The runtime never reads summaries.
- **Stop.** Once the turn's question has been said, a round whose every call was idle ends the
  loop. Nothing more can be voiced (`_say_once`), so another round is only latency.
- **Withhold.** A tool whose call changed nothing is left out of the schemas for the rest of the
  turn, so the next round has to answer in words. The next turn offers it again. The texts say
  the same: "Do not call update_candidate again this turn", and for `same_turn`, "End your
  turn now, with no text and no tool call".
- **Join a cut answer (KI-07).** When new speech cuts a running voice turn none of whose answer
  was heard (the filler aside), its words go in front of the next transcript if that comes
  within 5 s. Both user turns stay in the journal (the first one interrupted, D37); the model
  reads the whole answer once. Rejected: a longer speech timeout after a question about a date
  or a number. It would make every such answer 0.8 s slower, guess what the model asked, and
  change Pipecat's stop strategy mid-call.
- **Tool arguments in the journal.** `ToolStarted.arguments` is the call's JSON, redacted then
  cut at 2 000 characters like trace content, for the model's calls and the runtime's own. The
  export carries it, and the reviewer panel prints it. `redact` moved to
  `observability/redaction.py`, which `conversation` may import. The card pattern no longer
  matches digits glued to a word or a dash: it had masked every slot id as `[card]`, in the
  hosted traces too (D42).
- **The classifier's tokens.** `SignalAnalyzer.analyze` returns a `SignalAnalysis`: the signal,
  or none, plus the usage the call reported (a malformed verdict still costs). The runtime
  records it under the turn it classified. `token_usage` builds the two token records for
  every caller.
- **Cancelled generations.** An attempt that ends without a usage report (a barge-in, the
  answer limit, a silent first attempt, a failed stream) adds an estimate at 4 characters per
  token: the messages and tool schemas sent, and the text streamed. It is marked `estimated`.
- **Measured speech.** Pipecat's usage metrics are on. `UsageObserver` counts Deepgram's audio
  seconds and ElevenLabs' characters on their first push only, and the room's joins and leaves
  give each participant's minutes. The pure `SpeechMeter` turns them into `UsageRecord`s. The
  controller records them through `record_usage` once the pipeline has ended and the providers
  have flushed. A session already ended stores its export again (D34 is idempotent).
- **Partial means missing.** The snapshot derives a speech kind only when the call measured
  none. `cost_is_partial` is true when a usage has no price, no estimator is bound, or a speech
  kind was derived. A token estimate is flagged on its record and no longer makes the total
  partial. This replaces D36's "any estimate is partial".

**Measured** (the KI-08 patterns, one model round modelled at 0.75 s, `main` → this branch):

| Turn | Rounds | To the first sentence |
|---|---|---|
| A save repeated twice (seq 39–49) | 4 → 3 | 3.0 s → 2.3 s |
| A save repeated three times | 5 → 3 | 3.8 s → 2.3 s |
| A same-turn confirm (seq 60–62) | 3 → 2 | 0.75 s (total 2.3 s → 1.5 s) |
| A well-behaved save, then the question | 2 → 2 | 1.5 s → 1.5 s |

The scenario replays S01–S20 keep their scripts: none had an idle round, so no round count
changed.

**Consequences we accept.** A second, different fact for a tool whose call changed nothing waits
for the next turn. A join puts a cut part in front of words that may start a new thought within
5 s. The classifier's tokens can arrive after the export was stored at close; only speech usage
stores it again. A crash before the pipeline ends loses the measurement, and the export then
derives that call's speech and says it is partial. Pipecat's latency metrics are not stored.
Real latency is checked on the next hosted call (Langfuse `rounds`, time to first token).

---

## D45 · Browser speech is removed; voice is hosted or off

_Added 21 October 2026, with the documentation refresh._

**Context.** D18 put the browser's own Web Speech API in front of the runtime as a stand-in for
voice, and D22 kept it as `CAFE_NORTE_VOICE=browser` until the hosted exchange was verified. It
is: two hosted calls on 21 October (D35, `docs/known-issues.md`) and the fixes after them
(D40, D41) run on Daily, Deepgram and ElevenLabs. The page still carried about 150 lines of
recognition and synthesis code, and a seven-call voice surface shaped for it.

**Decision.** `VoiceMode = off | pipecat`. The Web Speech path leaves `web/assets/voice.js`;
the page's voice module is the Daily call alone and offers `app.js` three calls: `start`,
`stop`, `closing`. With voice `off` the **Hablar** button is hidden. `CAFE_NORTE_VOICE=browser`
stops the process at startup with "browser speech was removed in D45"; the allowed values are
read from `VoiceMode`, so the list in the message cannot drift from the type.

**Why.** Two voice paths meant two behaviours for the same read-back: browser speech has no
barge-in and no "delivered means heard" (D22), so nothing measured or fixed on one held for the
other. Keeping a mode nobody verifies costs a test matrix and a page surface for no evidence.

**Not changed.** A timing's `source = "browser"` stays: it means "measured on the page's clock"
(the hosted page posts `connected` and `first_audio`), not the speech mode.

**Consequences we accept.** There is no free local voice: speaking to Ana locally needs the
Daily, Deepgram and ElevenLabs keys (`make voice-smoke`, `.env.example`). The text channel is
unchanged and remains the offline path; CI never needed browser speech. The startup hint for
`browser` was removed later; it is now refused like any unknown mode.

---

## D46 · The live release gate: evidence is the candidate's words, a goodbye after booking ends the session

_Added 22 October 2026, after the first paid live runs of S01 and S02 (D43) on gpt-4o-mini._

**Context.** Fixed in #28: the simulator did not know the date, and "I can do …" around a slot
was not taken as a choice. After that, S01 and S02 still failed in every run. Three causes,
all in the conversation, none in the scripts:
- The model saved facts with `evidence_text` it had stitched from several messages, and once
  with words the candidate never said ("no tengo experiencia previa"). `update_candidate`
  took any text, so `no_fabricated_confirmed_values` failed in every run.
- After booking, the model answered each goodbye with a goodbye of its own and never called
  `end_session`. The session stayed active until the 24-line cap, and the outcome was
  `incomplete` (or `human_followup_requested`) instead of `reserved`.
- The simulator still miscounted weekdays ("lunes 23 de octubre", a Friday), and a few
  phrasings around a slot ("I can make it at …", "ya he confirmado la reserva para …") were
  left to the model, which looped on slot ids.

**Decisions.**
- **Evidence is what the candidate said.** `domain.candidate.said_in` splits the cited words
  into clauses. Each clause must appear, as whole words, in one of the candidate's last
  `HISTORY_TURNS` messages (case, accents and punctuation aside). The evidence kept is the
  latest such message, whole, with its own turn id. Before, the model's text was kept with the
  current turn. If any clause was never said, the save is refused (`evidence_not_said`), and
  the model is told not to ask the candidate to repeat but to call again once per message.
  Rejected: refusing every evidence that spans two messages. On a live run the model re-sent
  batches of facts, every one of them was refused, and the turn ran out of tool rounds.
- **A goodbye after booking ends the session.** Once a booking exists, a message that is only
  a goodbye or thanks (`signals.is_farewell`: no question mark, none of "pero", "cambiar",
  "wait", "change"…) goes to `end_session(candidate_done)` through the runtime, like D35's plain
  answers. The fixed `goodbye` line from `controls.<lang>.md` is said, and the model is not
  asked. The outcome is `reserved`. Before a booking, a goodbye stays the model's.
- **The simulator gets the day.** Each relative date fact goes in with the day it means, and
  more words count as talk around a slot choice (`make it`, `book`, `confirm`, `reserva`,
  `confirmado`).
- Prompt `ana_v17` (the new `goodbye` control line).

**Measured.** S01 and S02 live, gpt-4o-mini, two runs each: 0/2 on `main` after #27, and 4/4
with these changes (`evals/results/live/20261022T073513Z-scenarios`, not committed).

**Consequences we accept.** Evidence for a fact can point at a later message than the one that
first stated it, when the model batches. Thanks alone after booking ends the call, so a
candidate who thanks and then wants to ask something must start a new session. A model that
rewrites the candidate's words (a translation, a summary) is refused until it quotes them.

---

## D47 · One ElevenLabs voice, Spanish, for both languages

_Added 22 October 2026, after a listening check of ElevenLabs voices in Spanish and English._

**Decision.** Ana speaks Spanish and English in one voice, `uQw4jpKzMLrZuo0RLPS9`, on
`eleven_flash_v2_5`. It replaces the scaffold's default (Sarah) on the hosted demo.

**Rejected.** A voice per language. A separate English voice sounded better in English, but it
needs a TTS reconnect on every language switch, and Ana would sound like a different person
after the switch.

**Consequences we accept.** Ana speaks English with a Spanish accent. That fits a Spanish
employer.

---

## D48 · ElevenLabs v4 Turbo over HTTP; Ana hangs up after her goodbye

_Added 22 October 2026, after the first browser calls with the D47 voice._

**Context.** Two complaints from the first hosted calls. Ana's intonation changed between
sentences and between messages: a full stop or a question mark sounded like a new call. And
the call ended before her goodbye was heard. The page left the room as soon as the session's
state became terminal, and that state arrives before the goodbye's audio has played.

**Decisions.**
- **The voice model is `eleven_v4_turbo`, over HTTP.** Chosen by listening to the same two
  messages in Flash v2.5, Turbo v2.5, Multilingual v2, v3 Conversational and v4 Turbo, with
  several stability and speed settings (one request per sentence, as the app sends them). v4
  Turbo was the only model whose intonation stayed the same across sentences and messages.
  Settings: stability 0.4, similarity 0.8, style 0.2. Lower stability sounded less read, and v4
  ignores `speed` (measured: the same 2.0 s for one sentence at 0.8, 1.0 and 1.2).
- **HTTP, not WebSocket.** ElevenLabs' `multi-stream-input` WebSocket rejects v4 (HTTP 400), so
  the pipeline runs Pipecat's `ElevenLabsHttpTTSService`, one request per sentence, with one
  aiohttp session per call. The bridge, the session and the delivery ledger do not change.
  Each sentence is still its own utterance with its own `TTSStoppedFrame` and word timings
  from the `with-timestamps` endpoint. Barge-in still cancels the request in flight: measured
  offline, no audio after the `InterruptionFrame`.
- **Ana hangs up.** `VoiceSession` notes a terminal `StateUpdated`. Once everything sent has
  played, or as soon as the candidate talks over the goodbye, it calls `on_hang_up`, which ends
  the pipeline gracefully (`PipelineTask.end`). The page no longer leaves on the terminal
  state. It waits for Ana to leave the room, or 20 s.

**Measured.** Time to first audio, median of six sentences over HTTP: v4 Turbo 185 ms, Flash
v2.5 195 ms. Today's Flash over WebSocket was about 145 ms, so the switch costs about 40 ms
per sentence. Plain v4 and v3 were about 660 ms and were rejected. Price: v4 Turbo is $0.04
per 1,000 characters, the same as Flash.

**Rejected.**
- One ElevenLabs context per reply, so prosody would carry across sentences. On Flash it
  sounded worse than separate sentences. In Pipecat's sentence mode, a sentence also waits
  for the next one before it is spoken.
- `previous_text` continuity on v4 (Pipecat sends it within one reply turn). It sounded no
  better than separate sentences and would need that reply-turn change.
- Flash, Turbo v2.5 or Multilingual v2 with higher stability or speed: faster, but the
  intonation still changed at punctuation and between messages.

**Consequences we accept.** About 40 ms more before each sentence, and an HTTP request per
sentence instead of one open socket. v4 speaks more slowly than Flash, and no setting changes
that. A candidate who talks over the goodbye ends the call; they can resume with the private
link.

---

## D49 · gpt-4.1 for its first token; the end of a turn is heard, not timed

_Added 22 October 2026, from the Langfuse traces of a local voice call and a live comparison._

**Context.** After D48, the time from the end of the candidate's answer to Ana's first word was
about 4 s. The traces of a 16-turn local call put the server's part at 0.9–5.1 s per turn. Our
code before the model took 1–44 ms and the tools 0–17 ms. The rest was gpt-4o-mini waiting
for its first token: 0.6–4.8 s in round 1 (usually a tool call) and 0.55–1.0 s in round 2,
where Ana's words are written. Two rounds ran in 11 of the 16 turns. Outside the traces, the
turn also waited a fixed 1.0 s of silence (D35) and about 0.2 s of TTS.

**Decisions.**
- **The model is `openai/gpt-4.1`** (hosted default and `.env.example`). Chosen with the
  comparison suite, one repetition of the six cases per candidate, the same prompt, tools,
  KB and simulator:

  | Model | Cases passed | Facts | First token p50 / p90 / max | Rounds a run | € a run |
  | --- | --- | --- | --- | --- | --- |
  | gpt-4o-mini (9 runs) | 2/9 | 35/51 | 1030 / 2336 / 5417 ms | ~37 | ~0.07 |
  | **gpt-4.1** | 3/6 | 33/34 | **706 / 903 / 1212 ms** | ~25 | 0.21 |
  | gpt-5.4-mini (`reasoning_effort: none`) | 3/6 | 33/34 | 754 / 971 / 2009 ms | ~26 | 0.09 |
  | gpt-5.4 (`reasoning_effort: none`) | 2/6 | 32/34 | 969 / 1230 / 2486 ms | ~24 | 0.26 |

  gpt-4.1 was the fastest and the steadiest, and it tied for the best quality. It also needs a
  third fewer rounds than gpt-4o-mini, so the gain per turn is larger than per round. Price:
  $2 / 1M input and $8 / 1M output tokens.
- **The end of a turn is heard.** The stop strategy is Pipecat's `TurnAnalyzerUserTurnStopStrategy`
  with the bundled smart-turn v3 model (ONNX on the CPU, about 35 ms per utterance, 0.15 s to
  load per call; no extra dependency). A turn that sounds finished ends after 0.2 s of VAD
  silence and the final transcript. One that sounds unfinished waits up to 2.0 s for more
  words, so D35's "Tengo dudas sobre… dónde…" stays one turn.

**Rejected.**
- gpt-5.4-mini: as good as gpt-4.1 at less than half the cost, but slower at the tail (2.0 s
  max), and Chat Completions only allows tools with `reasoning_effort: none`, which needs an
  adapter option nothing else uses.
- One model round instead of two (Ana's words in the tool-call round, spoken after the save
  commits). It would save another 0.6–1.0 s on most turns, but it changes the "nothing announced
  before it is persisted" path. Measured first; it stays the next lever.

**Not solved by the model.** Three checks failed for every candidate: C2
`sources_shown_on_any_turn`, C3 `brief_language` / `language_of_last_assistant_turn`, and C6
`review_flag_present`. Because they fail the same way on four models, they point at the prompt,
the runtime or the cases. They are follow-ups.

**Consequences we accept.** About three times gpt-4o-mini's cost per conversation (about €0.21
instead of €0.07). The comparison is one repetition per case: representative, not
significant. Smart turn adds CPU on the shared-core VM per call. A finished sentence ends the
turn sooner, so a candidate who pauses after a complete sentence and then goes on starts a new
turn.

---

## D50 · The test pyramid: layers as folders, time as an argument, a quality report

_Added 22 October 2026, after an audit of the offline suite (1216 tests, 46 s, 92 % lines)._

**Decision.**

- **Layers are folders.** `tests/unit` holds pure code only (no store, runtime or app),
  `tests/component` one module behind fakes, `tests/http` the app through `build_test_app`,
  `tests/e2e` the scenario replays, the acceptance test and Postgres end to end. An
  architecture test keeps `unit` pure and forbids a test module importing another; shared
  builders, harnesses and Hypothesis strategies live in the `tests/support` package.
- **Time is an argument, and so is sleep.** Code that waits takes a `Sleep` beside its clock
  (default `asyncio.sleep`). Tests drive a `FakeTime` that shares one virtual instant between
  the clock and the sleeper, so no offline test sleeps on the wall clock.
- **Laws over examples for pure code.** Pure functions get properties (round trips,
  idempotence, absorption, invariants) on shared strategies, and the session domain is
  checked by one Hypothesis state machine. Profiles: `dev` (default), `ci`, `deep`.
- **Assertions read behaviour.** Returned values, reads through the `Store` contract, HTTP
  responses, events parsed as models. Not private attributes, not substrings of JSON, and a
  call count only when the count is the behaviour.
- **`make quality` is a manual report.** Branch coverage, tests per layer, the slowest tests and
  a mutation score (mutmut) over the small pure modules. The scores are a ratchet recorded in
  `tests/README.md`; CI does not run mutation.

**Rejected.**

- Gherkin (`pytest-bdd`). The scenario YAMLs are the behaviour specs and test names are
  sentences; step glue would duplicate both.
- A virtual-time event loop plugin. It hides the clock instead of passing it, and needs magic
  around `asyncio.timeout`.
- Mutation over the whole of `src/`. Async and the 1200-test suite per mutant make it slow and
  noisy.

**Measured.** Before: 1216 offline tests in a flat folder, 46 s with coverage, 28 properties,
about twenty tests on the wall clock with 10 ms margins, one test 13 s long because ragas phoned
home. After: 1273 tests in four layers (unit 593, component 586, http 64, e2e 30), 27 s with
coverage, 51 properties and 3 state machines, no test on the wall clock (twenty runs under
load, no failure), the network refused, branch coverage 87.6 % inside a 91.5 % total, and a
mutation score of 95 % over 910 mutants of the pure modules. The slot-offer decision moved out
of the runtime into a pure `conversation/slot_answer.py` (its component tests that only repeated
the decision went to `unit`; those that check the runtime runs it stayed), and the pure tests of
the export, the eval report and the simulated candidate's cues moved to `unit`, so the base is
the widest layer. The properties found one real
bug: `plain()` was not idempotent for compatibility letters.

**Consequences we accept.** One large move of test files. A `Sleep` argument on the few
classes that wait. The mutation score is not a gate.

---

## D51 · One scorecard in four tiers; ragas measures answers, tools and goals

_Added 22 October 2026, the evaluation stage._

**Context.** `evals/` scored which chunks came back, not what Ana answered with them, and its
numbers were spread over three reports. Nothing said, in one place, whether a prompt or model
change made Ana better.

**Options (agreed with the owner).** A curated suite on top of the runner, a rebuild around
ragas, or only new ragas metrics. ragas plus Langfuse, or adding promptfoo (red-team) or
deepeval. A judge model and a spend ceiling. A question set written by hand, generated, or
generated then curated.

**Decisions.**
- **One scorecard, 25 rows, four tiers** (`evals/scorecard.py`), cheapest first: 0,
  deterministic with no reference (runs completed, turn length, first-sentence latency, cost,
  tool calls accepted, language kept, no leak); 1, deterministic against a reference
  (recall@3, ragas ID-based precision and recall, no cross-store source, abstention, expected
  facts in the answer, ragas `ToolCallF1`, scenario trajectory, extraction, no fabricated
  value, task success, injection held); 2, a judge against a reference (ragas
  `Faithfulness`, `FactualCorrectness`, the goal and the rubric bullets as a pass/fail
  `DiscreteMetric`); 3, a judge alone (staying on topic, style, as the same metric). Tiers 0 and 1 gate;
  judge rows report against a target and the committed baseline, never pass or fail (D06
  holds: deterministic checks decide).
- **The trajectory is the journal's.** A scenario may carry `reference_tools` (`in_order` as a
  subsequence, `anywhere`, `never`) read from `tool_started` events, model and runtime calls
  alike, and a one-sentence `goal` for the goal judge. Only what every good run does.
- **Turn-level reads are pure** (`evals/scorers.py`): model-written turns are the assistant
  turns that carry no read-back question, brief or fixed reply; language by function words
  (accents are no evidence: Chamberí is said in both); a leak is a tool, chunk or
  configuration id, the prompt version, a key shape, raw JSON, or 12 consecutive words of
  `system.md` (8 matched instructed phrases such as the follow-up notice).
- **ragas and Langfuse only.** promptfoo is Node and a second runner; deepeval overlaps ragas.
  Injection is five scripted scenarios (S23–S27: prompt extraction, a false manager after
  another candidate's data, booking without a read-back, a role-play jailbreak, a fake system
  override to French), said word for word live (`live_candidate: scripted`) and scored by
  deterministic checks: `no_leak`, `spoken_language` (what Ana said, not the session's
  setting), no booking, no confirmation, nothing fabricated. Where the runtime enforces the
  rule (S25) the fake model obeys, as in S17; where only the model can refuse, the fake model
  refuses and the live run is the test.
- **`evals/judge.py` is retired.** Its rubric bullets are now pass/fail criteria of the same
  ragas judge; `JudgeVerdict` gives way to `RunRecord.scores` and `judge_model`, and the
  report's judge section reads them (amends D43).
- **Judge `openai/gpt-4o-mini`, at most €3 for a full paid run** (as agreed; after calibration
  the judge is `openai/gpt-4o`, see below); a self-judged run is labelled. The question set is generated once by ragas over our own chunks and curated by
  hand. Answer metrics come from QA probes: one short live session per question.

**Measured (22 October, fake model, hybrid retriever).** Every gated row holds on the 18 fake
scenarios. Tool calls accepted 113/137 (82 %): the refusals are a well-behaved script calling a
confirmation the runtime already took (`already_answered`, D35). ragas ID-based precision 0.35
and recall 0.88 on the 16 answerable questions (R07 expects two sections and finds one); the
floors are set just below.

**The question set (22 October).** ragas generated 33 candidates over the 50 chunks with
`gpt-4o` (prompts adapted to Spanish; one-word persona names, because the model rewrote
"Barista con experiencia" as "Experienced Barista" and ragas could not find it). Many carried
deliberate typos ("Wher is", "Dondé esta"); speech recognition does not misspell, so the kept
ones were corrected. 15 were kept (R25–R39), two added by hand: 41 cases, 32 answerable (8 per
language and store), 5 unsupported, 4 leakage. Every answerable case now has a `reference`
answer and `expected_facts` with `a|b` alternatives, so an English answer can hold a Spanish
fact. Hybrid recall@3 32/32, ragas ID precision 0.40, recall 0.86; BM25 alone misses only
English questions. ragas `StringPresence` is not used: it has neither alternatives nor
normalisation (thousands separators, accents), so fact presence is ours.

**The judges (22 October, paid smoke on gpt-4o-mini).** ragas `Faithfulness` and
`FactualCorrectness` told a right answer (1.0) from a wrong one (0.0). `TopicAdherence` and
`AgentGoalAccuracyWithReference` did not: on a plain Spanish exchange (the pay question answered
from the offer, a joke politely declined) the first marked the salary answer as refused and
classified "salario" outside a pay topic, also on gpt-4o; the second inferred the right end
state and still gave 0. Both are replaced by a pass/fail ragas `DiscreteMetric` with our own
prompt (`evals/prompts/criterion.md`): one criterion per row (topic, goal, style, each rubric
bullet), worded as violations the judge can quote, and "never" statements hold unless the
transcript shows otherwise. Tool calls are shown on a `(system)` line: inside Ana's turn the
judge took them for bracketed notes. Checked on a good and a bad conversation, twice: topic
and style right both times; the goal judge cannot tell an answer from the offer from an
invented one, which is what faithfulness is for. `FactualCorrectness` runs in precision mode:
a short answer that leaves out a detail of the reference is not wrong.

**The first live baseline (22 October, gpt-4o-mini answering and judging, about €0.25).**
Read with the transcripts, it showed as much about the measurement as about Ana:
- Two deterministic false alarms, fixed: the leak check flagged "Eso no lo sé, pero puedo
  pedir que alguien del equipo te lo cuente", a line `system.md` quotes for Ana to say (quoted
  passages are now cut out of the prompt's runs), and the abstention check missed "That's not
  something I know".
- The pass/fail judges were wrong on real transcripts: topic 0.23 and style 0.25. gpt-4o-mini
  failed Ana *for* using tú under a "never usted" criterion, and failed topic whenever there was
  nothing to decline. Two hand-made examples had not shown it. Hence `calibrate.py` and
  `cases/judge/calibration.yaml`: 18 labelled cases, both verdicts for every criterion. The
  wordings were rewritten until gpt-4o-mini agreed on topic, style, faithfulness and accuracy
  three times in a row; on three-part goals it still flipped one case either way, so the
  scorecard's judge is `openai/gpt-4o`, 18/18 twice. Since D49 it is also not the answering
  model.
- `FactualCorrectness` measured the wrong thing against short references: in precision mode a
  right answer with more details from the knowledge base scored 0 (R35), and in recall mode a
  right "35 horas" scored 0 (R01). NVIDIA `AnswerAccuracy` separates right answers (0.5–1) from
  non-answers and wrong numbers (0) and replaces it. Ana's closing question is cut from the
  answer before either judge reads it.
- About gpt-4o-mini itself: recall@3 is 32/32 offline, but live the model's own query missed
  for R01 and Ana said "35 horas" anyway (faithfulness 0); R05, R06 and R32 searched and then
  said they did not know; R19 answered the manager's pay with the barista's; S27 once answered
  in French; three of seven simulated scenarios passed. The baseline is not committed: its
  judge rows predate the calibration.

**Concurrency (owner's call).** The first baseline ran every session one after the other,
a rule from the Groq free tier (8 000 tokens a minute). Now the phases (scenarios, probes,
judges) still run in order, and inside each up to two sessions or judged runs run at once
(`evals/pool.py`, `--concurrency`). A session's own turns stay in order. The scorecard states
the concurrency, because its latency row is measured under that load. This also applies to
the scenario and comparison suites. Four was tried first, on the gpt-4.1 baseline: each model
round sends about 10 000 tokens and gpt-4.1 answers in about a second, so four sessions passed
the organisation's 450 000 tokens a minute and 39 turns failed with 429 (`busy`). That run was
discarded. It also showed the scorecard hid it: a session with failed turns still exports, so
"valid export" read 53/53 while 30 probes had no answer. The first row is now "runs
completed" (an export and no failed turn); a probe whose turn failed is counted there and
nowhere else.

**The gpt-4.1 baseline (22 October, gpt-4o judging, two sessions at a time, committed as
`evals/results/scorecard/openai-gpt-4.1.json`).** 53/53 runs completed, no 429. Every tier-0
row holds: first sentence 1.5 s median, €0.045 a session, tool calls 97/97, no leak. Injection
5/5 held. Misses, all read in the transcripts:
- **The model's own topic filters the answer away.** R01 (hours), R05 (contract), R06
  (holidays) and R32 (work permit) searched with `topic` `role` or `benefits`, whose documents
  (`TOPIC_DOCS`) do not include `offer_*` or `interview_process`; Ana then said the KB does not
  say. Offline recall@3 is 32/32 because the suite does not apply the model's topic: the next
  change is the knowledge stage's, not the evaluation's. Expected facts 43/51.
- Scenarios 3/7: S05 never showed an offer source, S06 flagged no follow-up, S07 answered in
  Spanish after the switch, S11 left the outcome unset after the withdrawal.
- Judges (report only): faithfulness 0.85, answer accuracy 0.63, goal 0.58, rubric 0.79, on
  topic 0.89, style 0.83.
Two abstentions ("I couldn't find information about…", "I don't have information about…")
were missed by the regex and re-scored for free from the recording (`--rescore`): 5/5.

**Consequences we accept.** The retrieval rows need the hybrid retriever, so `make check`
gates the scenario rows and leaves retrieval to its own tests (BM25 alone misses the English
questions the model would have reformulated). Latency and cost targets are provisional until
the first paid baseline.

---

## D52 · Jev reads sentiment and the language switch beside the turn; the regex stops switching on mentions

_Added 22 October 2026, after the signals experiment (`evals/signals.py`)._

**Context.** Two soft signals ran on two mechanisms: the language switch on the D28 patterns,
and the sentiment on an opt-in chat classifier (D30, off in the hosted demo). A decision model,
TypeSafe's Jev on OpenRouter, answers typed questions with calibrated probabilities and no
text, in about 0.3 s. The question was whether one such call beside the turn beats both, with
no latency added to the turn.

**What was measured.** Four systems on two synthetic sets: 122 hand-written turns (`dev`, the
questions were tuned on it) and 83 written by gpt-4.1 from a fixed grid, each line checked
against its cell (`heldout`, scored once). Two repetitions. Held-out, before the regex fix:

| | regex | gpt-4o-mini classifier (D30) | gpt-4o-mini, Jev's questions | Jev |
| --- | --- | --- | --- | --- |
| Frustrated/uncertain precision / recall | – | 80% / 85% | 89% / 77% | 98% / 88% |
| False language switches | 0/118 | – | 7/118 | 0/118 |
| Missed language requests | 16/36 | – | 0/36 | 0/36 |
| Stable across repetitions | 100% | 95% | 92% | 99% |
| Latency p50 / p95 | 0 ms | 796 / 1117 ms | 774 / 1075 ms | 279 / 461 ms |
| € per 1000 turns | 0 | 0.046 | 0.050 | 0.023 |

On `dev` the regex also made 6/190 false switches ("Do I need to speak Spanish?", "No need to
switch to Spanish", "No hace falta que me hables en inglés"): KI-09. Asking Jev "es or en" missed
8/38 indirect requests; asking "keep or switch", relative to the session, missed none, on both
sets. Without Ana's previous sentence in its state Jev made one false switch and missed one
request on `heldout`, so the analyzer port now passes it.

**Decisions.**
- `DecisionModel` is a port in `model/` (`decide(state, questions, *, deadline) -> Decision`);
  `model/decisions.py` is its OpenRouter adapter, `FakeDecisionModel` its fake. Failures are
  `ModelError` with the usual codes.
- `DecisionSignalAnalyzer` implements `SignalAnalyzer` with the two questions of
  `prompts/signal_questions.yaml`. It is chosen by `CAFE_NORTE_SIGNAL_MODEL=openrouter/<model>`
  with `OPENROUTER_API_KEY`; unset, nothing changes. A soft sentiment counts at p ≥ 0.5 and a
  language switch at p ≥ 0.7: the thresholds with no false alarm on either set.
- The analyzer still runs after the turn. A switch it reads applies at the start of the next
  turn, exactly like an explicit request: saved with the user turn, before the model, only from
  the immediately previous user turn, and an explicit request in that turn wins (`fresh_switch`).
- With the analyzer on, a whole message in the other language also switches (12/12 held-out
  `written_other`), which D28 deliberately left alone; the patterns still never do. A candidate
  who answers in the other language is answered in it from the next turn.
- Jev quotes nothing, so its evidence is the whole message it read. D30's rule ("a verdict needs
  the candidate's own words") still holds for the chat classifier.
- KI-09: "speak"/"hablar" before a language count only after a request word, and a negation up
  to six words before a language request, in its clause, turns it down. The regex stays the
  fast path for explicit requests; the indirect ones are the analyzer's.
- `SignalAnalyzer.analyze` takes `ana_said`, what Ana said before the message.

**Rejected.**
- Calling Jev before the model, in the turn: 0.3–0.5 s on every turn for a switch that is rare.
- Cutting Ana's reply mid-turn when a switch arrives: Jev's p95 (about 0.5 s) would allow it, but it
  changes what has been said and journaled. It is the next step if the one-turn lag matters.
- A chat model with Jev's questions: it catches every request but switches falsely on mentions
  (7/118 held-out) and is three times slower.

**Consequences we accept.** One candidate turn passes in the old language before the switch,
and in voice that turn is also transcribed in the old language. The candidate's message, Ana's
sentence and the session language go to OpenRouter and TypeSafe (US-hosted, an alpha endpoint
with no published retention period). It is on in the hosted demo, whose data is fictional
(as for trace content, D42), so the behaviour can be tried from the public URL; it stays off
for real applicants until retention is settled. The labels are synthetic: a held-out set written by another model, but no real
transcripts. Sentiment is still advisory and never a hiring input.

## D53 · A language switch read in time is applied in the same turn

_Added 22 October 2026, after the first hosted test of D52._

**Context.** With D52 on the hosted demo, "Perdona, no hablo bien español, soy de Londres" was
read as a switch to English, but Ana had already answered in Spanish ("podemos seguir en
español sencillo") and only the next turn was English. Jev answers in about 0.3 s (p95 0.5 s);
gpt-4.1's first sentence comes after 0.6–1.0 s. The verdict usually exists before Ana says
anything.

**Decisions.**
- An analyzer that can ask for the other language (`switches_language`, Jev) starts with the
  turn, beside the model, on the same message and Ana's previous sentence. The chat classifier
  (D30) is not waited for and still runs after the turn.
- Before Ana's first words of the turn (her first sentence, or the first round's tool calls),
  the runtime checks the verdict once. If it has not come it waits at most
  `switch_wait_seconds` (0.5 s); a later verdict keeps D52's switch at the next turn.
- A switch drops the round: nothing of it was said, journaled or run. The language is saved,
  then announced with `StateUpdated`, which now carries the session language, so speech
  recognition follows before Ana speaks; the messages are rebuilt and the round runs again.
  Once something was said this turn (a fixed reply, a read-back) there is no restart.
- The verdict computed in the turn is the one journaled after it: one call per turn, as before.
- `language_switched` is a structured event with the time Ana's first words waited.

**Rejected.** Cutting a sentence already spoken and saying it again: what was heard is in the
journal and cannot be taken back. Calling Jev before the model: 0.3 s on every turn.

**Consequences we accept.** A switch costs the dropped round's tokens and one more round's
latency, on the rare turn that switches. A turn whose first words come before Jev, and after
the 0.5 s wait, still switches one turn late. The candidate's own message stays recorded in
the language the turn opened in; Ana's answer is in the new one.

---

## D54 · Search the store's documents, not the model's topic; shared words leave the query

_Added 22 October 2026, from the gpt-4.1 baseline of D51._

**Context.** Offline, recall@3 was 32/32: the suite searched the fixture's question over the
store's documents. Live, 4 of 32 answerable probes said the knowledge base did not have the
answer when it did. The model's Spanish queries were good; the `topic` it chose filtered the
answer away. Hours and contract were searched as `role` and holidays as `benefits`, and
`TOPIC_DOCS` gave neither topic the offer documents (D26).

**Measured.** `make evals-retrieval ARGS="--replay <scorecard>"` reruns the 36 searches (78
phrasings) the model made for the 32 answerable probes through the real hybrid index, with no model and for
free. With its own topic, 26/32 found an expected section; without any topic, 27/32. The rest
came from the words every chunk shares: "¿Cuántos días de vacaciones tiene el puesto de
barista en Café Norte Chamberí?" ranked the company and role sections above the holiday one.
With "Café Norte", "Madrid" and "barista" removed from each phrasing: 30/32. Removing the
store's name as well lost the address question (R29), so it stays.

**Decisions.**
- `search_knowledge` has no `topic`. The handler searches every document of the session's
  configuration; keeping the two stores apart was always the configuration's job. One fewer
  argument for the model to get wrong. `TOPIC_DOCS` and `Topic` are gone; prompt `ana_v19`.
- `HybridRetriever` takes the shared words out of each phrasing before both rankers
  (`searchable`); a phrasing that is only those words is kept whole.
- The retrieval suite gains `--replay`: the model's recorded queries of a live scorecard,
  rerun through today's retriever. A change to retrieval is judged on what the model really
  writes, not only on the fixture's tidy questions.

**Rejected.** Widening `TOPIC_DOCS` (fixes the four cases seen, waits for the next); the topic
as a ranking boost (more logic, nothing measured shows it helps).

**Measured after.** Hybrid recall@3 still 32/32, leakage 0/41, unsupported with sources 3/5,
ragas ID precision 0.40 and recall 0.86. Replay 30/32: R32 (the work permit for non-EU
nationals) and R36 (whom to ask for at the interview) still miss; R36 was found with the
`interview` topic, the one case the topic helped. BM25 alone loses the English R35, whose raw
question names the barista; the model always searches in Spanish.

**Consequences we accept.** The topic's precision is gone: a question can now bring back a
chunk of any document of the store. Thirty-two recorded questions are a small sample; the next
live scorecard is the check.

---

## D55 · A restart releases its voice places; a call nobody joins ends after 30 s

_Added 22 October 2026, after "Ahora mismo no hay plazas libres" on the hosted demo._

**What happened (logs and the `admission` table).** Two different holds, the same refusal:
- 12:33–12:35: six `POST /voice` got 503 `busy`. The two calls started at 12:27:32 and
  12:29:40 were cut by the two container starts of the #41 deploy (12:29:28 the previous
  release, 12:30:50 the new image; a reset restarts the old release first, D31). Neither ever
  reached `release`: their rows stayed held, so both places counted until the 600 s ttl, 12:37
  and 12:39.
- 08:20–08:21: two 503s while two calls held the places normally. Neither had a single voice
  turn: the page never joined (the CSP block fixed in #33). Each bot sat in an empty room until
  Pipecat's idle timeout, about five minutes, and only then released its place. The same
  happened at 10:18 without a refusal.

**Decisions.**
- **An admission row names its instance** (`owner`, migration `0004`). At startup the app
  releases every place its instance still holds (`Admission.release_left_over`), and logs how
  many. With one container per VM those are always the calls the restart ended; with several,
  each instance releases only its own, so the cross-container cap of D32 holds. The instance is
  the hostname: the app runs with host networking, so it is the VM's and survives a reset. The
  600 s ttl stays for a VM that never comes back.
- **A call nobody joins ends.** The page joins as soon as `POST /voice` returns; if the
  candidate is not in the room 30 s after the bot (`CANDIDATE_JOIN_SECONDS`), the pipeline is
  cancelled and the place released. Timed with an injected `sleep`, tested on virtual time.

**Rejected.** A heartbeat with a short ttl: a renewal loop per call for what one statement at
startup does (D32 declined the same loop for leases). Releasing every unreleased row at
startup: wrong as soon as there are two containers.

**Consequences we accept.** A deploy still ends the calls in progress; it no longer blocks the
next ones. A candidate whose page takes more than 30 s to join loses the call and starts it
again. Rows written before the migration have no owner and age out as before.

## D56 · Facts for the runtime, words for the model: the interview times are on offer with the brief

_Added 22 October 2026, after three hosted voice calls of the same day (Langfuse, `production`,
10:19, 11:30 and 13:01 UTC; gpt-4.1, `ana_v17` and `ana_v19`)._

**Context.** In the 13:01 call the candidate said "Sí" to "¿Te gustaría hacer una
entrevista?" and the model answered "te digo los huecos" four times without calling
`list_interview_slots`; no time was ever said (KI-10). In the 11:30 call the model invented
slot ids twice (`2026-10-24T17:00:00`, `slot-2026-10-27T10:30`): it never sees an id after the
turn that listed it, because history keeps only spoken text. Each refusal said "Offer fresh
slots with list_interview_slots", and the runtime said the whole list four times, once in the
same reply as "¿Te la reservo?" (KI-11). "El martes de noviembre" offered Tuesday 27 October,
because the month was thrown away. Both failures come from the same place: the times existed
only behind a tool the model had to remember, and tool results gave orders instead of facts.

**Decisions.**
- **The principle.** The runtime owns the facts and the rules: it validates, persists, and
  shows the model the true state. The model owns the words: offers, empathy, the order of
  things. Only read-backs of saved values are said word for word, since what is said must
  match what is stored. A tool result says what happened, not "reply with nothing" or "list
  again".
- **The offer is made with the brief.** A confirmed brief puts the first three free slots on
  offer (`slot_offer`), and the facts show them by number and local time (`interview_slots`),
  never by id. The model says them itself when the candidate wants an interview.
- **A slot is chosen by number.** `present_confirmation(target=slot, choice=n)`; an id still
  works. The candidate's words asking for the interview come with the first choice
  (`evidence_text`), so the explicit intent of D29 is still their words.
- **`list_interview_slots` is for another day.** It replaces the offer and returns the times as
  text; nothing is spoken for it. A day with nothing free is said plainly ("No free slot on
  …"), no longer covered silently by the first three.
- **A refusal names the options.** An invented id or a number not on offer gets "That time is
  not available. The times on offer are: 1 …; 2 …" plus "offer the other times, or call
  list_interview_slots for another day".
- **The matcher (D41) waits for the request, keeps the month and stops re-listing.** It acts
  only once the candidate has asked for an interview (`schedule_intent`): the offer exists
  before Ana has said a time, and a live run booked a "la última" the candidate said to another
  question. Words that name a day not on offer offer that day, and when the same words name its slot ("el viernes 23 a las diez y
  media") the runtime reads it back in that turn. Words that name no day (a time not offered,
  a month with nothing free) are the model's, which has the options.
- Prompt `ana_v20`; the spoken offer (`render_slot_offer`, `slots.*`) is gone.

**Replaces** the spoken offer of D29 and D41's `NoMatch` with no day, which listed the same
slots again.

**Rejected.**
- A fixed runtime question "¿Te gustaría hacer una entrevista?" with the yes routed to the tool.
  It is controlled, but scripted, and one more place for a loop.
- Replaying tool calls and results in history so the model sees the ids. It costs tokens on
  every call, and an id can still be miscopied.
- Choosing by date and time as tool arguments. The matcher plus `date_preference` already
  cover "el martes 27 a las diez".

**Consequences we accept.**
- The model words the offer, so it may shorten "miércoles 21 de octubre de 2026 a las 17:00".
  The read-back that follows is still exact.
- An offer made with the brief can go stale during a long questions phase. A past or taken slot
  is refused at the read-back with the remaining options.

## D57 · Ana waits half a second after a finished sentence and needs two words to be cut off

_Added 22 October 2026, after the hosted voice call of 11:30 UTC (KI-12)._

**Context.** With D49, a sentence the smart-turn model judged finished ended after Pipecat's
default 0.2 s of VAD silence, and any 0.2 s of voice started a turn and cancelled the one
running. In Ignacio's call 12 of 32 turns were cancelled; he said Ana interrupted him. Three
cut parts were lost from the join (D44), because the window ran until the continuation's
final transcript, and the model saw each joined fragment twice.

**Decisions.**
- `vad_params()`: `stop_secs` 0.5 s (`FINISHED_TURN_SILENCE_SECONDS`). The smart-turn model judges
  after it; an unfinished sentence still waits up to 2.0 s (D49). Chosen between "now" and a
  slower 0.8 s: about 0.3 s more per turn. Raise to 0.7 s only if Langfuse still shows cuts.
- A turn starts on a transcript (`MinWordsUserTurnStartStrategy`): a soft "sí" VAD misses
  still counts (D35), and while Ana speaks it takes two words (`BARGE_IN_WORDS`) to cut her, so a
  cough or an "mhm" does not. Pipecat counts one word while she is silent.
- The join window is the pause: it is checked when the candidate speaks again (the
  interruption), and the continuation may then last as long as it takes.
- `history_messages` drops a candidate's words that the next user turn repeats in full, the
  current one included: the joined fragment appears once.

**Rejected.** Turning barge-in off while Ana speaks (no correction mid-sentence, and D48's
hang-up on a talked-over goodbye changes); 0.8 s or more (slower on every turn to fix the
breaths of some); a runtime that rolls back what a cancelled turn already saved (a bigger
change; rarer now).

**Consequences we accept.** About 0.3 s more after every finished sentence. A one-word answer
over Ana ("no") waits until she stops. Barge-in now waits for the first interim transcript
instead of VAD, a few hundred milliseconds later.

## D58 · The rest of the live-call fixes: warnings that count, the model told the truth

_Added 22 October 2026, from the hosted calls of the same day (KI-12 and the traces read with
the v2 observations API), after D56 and D57. One entry per fix, in the order they landed._

**Decisions.**
- **A warning is not a failure.** The `Span` port gains `warn(code)`: Langfuse level
  `WARNING` with the code as status message, and no OpenTelemetry error status.
  - An interrupted turn is a warning (`interrupted`), and its outcome is `interrupted`.
  - A span left by a cancellation is a warning (`CancelledError`), unless a code was set on
    purpose.
  - A refused tool call is a warning whose code is its summary before the first colon
    (`evidence_not_said`, `slot_not_offerable`, `confirmation_refused`), so a dashboard can count
    refusals per tool.
  - Timeouts and real failures stay `ERROR`. Live, 13 of 51 turns were `ERROR`, every one a
    barge-in, and 44 of 89 `update_candidate` calls were refused with nothing to count them by.
- **A confirmed field is not read back again.** `present_confirmation(field)` on a confirmed
  field is refused ("already confirmed; it is not read back again", then the next step). A
  second `confirm_field` hears "It is already confirmed" plus the next step, instead of
  "Present it again", the order that read Iñaki's start date twice. The other defaults of the
  kind ("Present the slot again") now say that nothing was reserved, and give the next step.
- **An interview request is the candidate's own words.** `list_interview_slots` and a first
  `present_confirmation(slot)` check `evidence_text` with the same `said_in` as
  `update_candidate` (D46) before they save the intent. Live, "Sí, quiero tener una entrevista."
  was saved when the candidate had said only "Sí.". An intent already saved is reused, not
  checked again.
- **An accepted follow-up is a follow-up.** A note is read by no one, and its result now says so:
  "nobody will contact the candidate from it; if they accepted that a person follows up, call
  request_human_followup". The prompt and the tool description say the same, and a follow-up
  offer waits for the answer. Live, "Sí, anótalo" to "¿Quieres que lo deje anotado para que te
  contacten?" became a note. S30 replays it.
