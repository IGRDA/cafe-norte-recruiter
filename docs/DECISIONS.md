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
