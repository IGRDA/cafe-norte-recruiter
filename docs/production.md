# Production discussion

Spec §17 asks what changes when this demo meets production, without building it. This document
answers from what exists: the decisions in `DECISIONS.md` (cited by number), the limits in
`architecture.md` and the numbers measured so far. Where a statement is reasoned and not
measured, it says so. There is no load test yet, so no figure here is a capacity claim.

Every section has the same four parts: **Today** (built, with numbers), **What breaks first**,
**Next step**, **Trade-off**.

| Pressure | Section | Built on | First to break |
| --- | --- | --- | --- |
| More simultaneous calls | [1](#1-more-simultaneous-calls) | D24, D32 | One VM's CPU and the providers' quotas |
| Multiple replicas | [2](#2-multiple-replicas) | D31, D32, D34 | Routing a call to the process that holds it |
| Higher availability | [3](#3-higher-availability) | D24, D33 | The single VM and the minute of downtime per deploy |
| Candidate imports | [4](#4-candidate-imports) | D32, D34 | Nothing yet: there is no import path |
| Background work | [5](#5-background-work) | D30, D34 | Work that dies with its process |
| Configuration changes | [6](#6-configuration-changes) | D12, D21, D36 | Nothing gates a change on live behaviour |
| Larger corpus | [7](#7-larger-corpus) | D26, D27 | The in-process index and the relevance floor |
| Monitoring at scale | [8](#8-monitoring-at-scale) | D36, D42 | No alert fires; dashboards are the Langfuse defaults |
| Regional voice quality | [9](#9-regional-voice-quality) | D22, D24, D35 | Speech recognition on short answers |
| Privacy with real applicants | [10](#10-privacy-with-real-applicants) | D34, D42 | Redaction is patterns, not people |
| Twilio telephony | [11](#11-twilio-telephony) | D01, D22, D38 | Read-backs that must be heard, with no screen |
| Native speech-to-speech | [12](#12-native-speech-to-speech) | D01, D35 | The guarantees that rely on owning every sentence |

## 1. More simultaneous calls

**Today.** Two voice sessions per container, counted in Postgres rows and not in memory (D32);
a third gets `busy`. One `e2-small` VM runs the app, Caddy and the Cloud SQL Auth Proxy (D24,
D33). A container holds five database connections, and each open event stream polls every
200 ms (D31). Groq's free tier allows 8k tokens a minute, which is why the hosted model is on
OpenAI (D23): `gpt-4.1` since D49, for its first-token latency. Each voice pipeline also runs the
smart-turn model on the CPU, about 35 ms per utterance on a laptop (D49).

**What breaks first.** Reasoned, not measured: the CPU of the voice pipelines on a shared-core
VM (each call runs VAD, the transport and the runtime's loop in one process), then the provider
quotas (model, Deepgram, ElevenLabs, Daily), then the pool of five, since a turn, a stream poll
and a heartbeat all need a connection. The cap of two is a cost guard first: euros are recorded
and not enforced (D32).

**Next step.** Measure before moving anything: run N synthetic `daily-python` candidates (the
one used for D24) against one VM and record CPU, first-sentence latency and `busy` rate per N.
Then split the API from session workers that hold the voice pipelines, and scale workers on
active calls, with the admission rows as the number.

**Trade-off.** Workers separate the thing that is cheap and stateless (HTTP, SSE) from the thing
that is heavy and sticky (a call). The cost is a second deployable and a routing problem (§2).
Raising the cap on the same VM is free and risks degrading every call at once.

## 2. Multiple replicas

**Today.** Several things already work across processes, because they live in Postgres.
A lease row per session with a generation that only grows: a turn claims it for 60 s and every
write is fenced on it, so a stale process cannot write (D32). Voice admission rows, which stop
counting after 600 s, so a container that dies frees its place by itself (D32). The event
sequence is owned by the store (D31). The retention purge runs under an advisory lock, so only
one container does it (D34). A restart already loses at most the turn in flight (D32; the
runbook).

**What breaks first.** A voice call is a process: the Pipecat task, the Daily connection and
the delivery ledger live in the worker that started it. Anything that needs that call
(`POST …/end`, a delete) must reach the same worker. Request affinity is not enough: it does
not survive the worker's replacement, and nothing records which worker owns which room. Second,
a worker that dies mid-call leaves the session `active` with no call: its turn lease frees in
60 s and its admission row in 600 s, but nothing pauses it (D35 pauses when a call ends, which
needs a live worker to notice).

**Next step.** Record the owner in the admission row (one column), route control calls by that
owner, and give a replacement worker a way to take over: expire the lease, then let the
resume path (D32) start a new room on the candidate's next **Hablar**, which is what a restart
does today. Move the event stream from polling to LISTEN/NOTIFY once streams per container
pass a few dozen (D31 named that threshold).

**Trade-off.** Taking over a call in place would be seamless but needs the audio pipeline's
state to be movable, which it is not. Resuming into a new room costs the candidate a
reconnect and keeps the design simple, because the journal and the lease already make a resume
safe.

## 3. Higher availability

**Today.** One zonal VM and one zonal `db-f1-micro` (D24, D33). A deploy resets the VM: about a
minute of downtime, and an open page reconnects (D24, runbook). Cloud SQL keeps three daily
backups and has no point-in-time recovery; deleting a session leaves its rows in backups for up
to three days (D33, D34). Standing cost is about 15 EUR a month for the VM and 8 EUR for the
database (runbook).

**What breaks first.** The VM: a zone outage or a bad boot takes the demo down, and COS patches
the host while the container is not patched (D24). Next, the database: a micro tier shares CPU
and its 10 GB HDD is slow; a failed instance means a restore from the last daily backup.

**Next step.** In this order: regional HA and point-in-time recovery on Cloud SQL, with a tier
sized from the §1 measurement; a managed instance group of two VMs behind a load balancer, with
draining (stop admitting, let calls finish, then stop); the uptime check and 5xx alert that
`infra/` does not provision yet. The reconnect path is the resume link (D32), valid seven days.

**Trade-off.** Each step multiplies the standing cost for a demo that needs none of it. A load
balancer also reopens the media question D24 settled: WebRTC needs a routable address per
worker, so the balancer fronts HTTP only and each worker keeps its own address for audio.

## 4. Candidate imports

**Today.** No import. A candidate opens the page and starts a session; sessions are gated by an
access code, three starts per access session per hour (`architecture.md`).

**What breaks first.** Nothing is built to break. The first import would break the providers'
quotas and a person's patience: a thousand calls started at once is a thousand simultaneous
rooms, and the cap is two.

**Next step.** A durable queue in Postgres: a row per candidate with a state, deduplication by
normalised phone number, a contact window by the candidate's local time, pacing set by the
admission count, retries with backoff and a maximum, and backpressure: when admission is full,
nothing is dequeued. The job claims a row with `FOR UPDATE SKIP LOCKED`, the same row-lock
discipline as the slot reservation (D31).

**Trade-off.** A queue table in the existing database costs no new service and is enough for
thousands of rows a day. A managed queue (Cloud Tasks, Pub/Sub) adds delivery guarantees we
would otherwise write by hand, at the price of a second place where state lives.

## 5. Background work

**Today.** Three jobs run inside the app process. The export stored when a session closes
(D34), the hourly retention purge at 100 sessions a round (D34) and the signal classifier after
each turn, with a 5 s deadline, where a late verdict is no signal (D30); in the hosted demo it is
Jev, which also reads a language switch for the next turn (D52). The narrative summary
is `skipped`: the deterministic brief is the deliverable (D34).

**What breaks first.** Work that dies with its process. A crash between the commit that ends a
session and the close hook leaves no stored export; the endpoint then builds it on demand, so
the cost is a rebuild and a logged failure, not a missing document (D34).

**Next step.** Durable jobs keyed by session id with an idempotent handler: `export`, `summary`,
`evaluation`, each a row with a state and attempts, drained by whichever worker holds the
maintenance lock. Idempotency is already the pattern: the export is an upsert and a booking
returns the same booking for the same key (D31, D34).

**Trade-off.** Jobs turn a lost side effect into a delayed one and give a place to retry, for a
table and a loop to maintain. A model-written summary would be the first job that really needs
it: it is paid, slow and optional, so it should never sit on the turn.

## 6. Configuration changes

**Today.** Prompts, knowledge and the configuration are files in the repository (D12).
`VersionStamp` (prompt, model, knowledge base, configuration, commit) is on every session, every
export and every trace span (D36). Scenarios replay against a fake model in `make check` (D21,
S01–S22), and the live counterparts are run by hand.

**What breaks first.** Nothing gates a change on live behaviour. A prompt edit that passes the
fake-model scenarios can still change how `gpt-4o-mini` behaves: D35 and the language stage
found that gap by hand, in real calls.

**Next step.** Immutable, versioned configuration rows validated at load. A change goes through
the scenario suite and the live evaluation, then a staged rollout (a share of new sessions
carries the new stamp), and a rollback is selecting the previous stamp. The stamp already makes
the comparison one filter in Langfuse.

**Trade-off.** Staging needs enough sessions to tell two versions apart; at demo volume it
would be noise. The first affordable step is the regression gate, not the rollout.

## 7. Larger corpus

**Today.** Twelve fictional documents, chunked by section at 90 words or fewer, filtered by
store before ranking, BM25 plus local multilingual embeddings fused by RRF, three chunks at
most (D26). A chunk with no keyword match needs cosine at least 0.40 (D27). Measured locally in
D26: recall@3 16 of 16 on answerable questions, 0 of 24 leaked across stores, a median of 6 ms
per retrieval after warm-up. At most two query embeddings run at once per process.

**What breaks first.** The index lives in each process and is built into the image, so a new
document is a new image. The 0.40 floor was measured on twelve documents and is a number that
moves when the corpus or the embedding model does (D27 says so). Filtering is by store, not by
tenant.

**Next step.** A retrieval service with a tenant filter applied before ranking, as store is
today, and an index built per knowledge-base version outside the image. Re-run the 24-question
suite and re-measure the floor at every corpus change. Add a reranker only if it improves the
suite's numbers, not because it is standard.

**Trade-off.** A service adds a network hop to a 6 ms step and a second thing to keep up. It
buys updates without a deploy and isolation between tenants, which a real corpus needs.

## 8. Monitoring at scale

**Today.** One Langfuse trace per candidate turn with stable span names, the version stamp on
every span, tokens and euros from our own price table, and JSON log lines keyed by session and
turn (D36). Since D42 the hosted traces carry redacted words and tool arguments, which is what
makes a bug like KI-06 readable. Failed-call triage is a documented path (runbook).

**What breaks first.** Nobody is told. There is no uptime check and no 5xx alert, and a failed
turn is a red span someone must open. Not recorded yet (D36): the signal classifier's tokens, a
cancelled generation's tokens and Pipecat's own STT and TTS metrics. Trace export is a bounded
queue of 2 048 spans that drops the excess, and a crash loses at most the last 2 s.

**Next step.** OpenTelemetry to Cloud Trace and Monitoring beside Langfuse, since the adapter is
plain OTel behind a port (D36). Alerts on the uptime check, on 5xx and on the rate of
`turn_failed`, `timeout` and `busy` events. Dashboards by configuration, language and model,
which the stamp already allows. A weekly review of a sample of conversations, chosen by outcome
and not at random.

**Trade-off.** Two backends double the places to look. Langfuse is better for reading one
conversation; Cloud Monitoring is better for paging someone at three in the morning. Keep both,
with one job each.

## 9. Regional voice quality

**Today.** Everything runs in `europe-west1`. Measured on the VM: `POST /voice` (room, bot
joined) returns in 3.5 s and DTLS completes in under 2 s (D24). A turn ends after 1.0 s of silence, which costs 0.4 s per spoken turn (D35). Deepgram runs
in the session language and follows a switch (D35).

**What breaks first.** Recognition of short answers: Deepgram `multi` heard "sí" as "C" and
"Sì", and soft answers started no VAD event (D35). Regional accents and phone-quality audio are
not measured at all.

**Next step.** Audition ElevenLabs voices with listeners from the target regions, and
evaluate speech recognition on recorded answers from those regions with the same scenarios, by
word error rate on the closed set that matters (yes, no, dates, numbers, phone digits).
Measure the route from the worker to each provider and place the worker accordingly where the
providers offer regions.

**Trade-off.** Per-region voices and recognisers improve quality and multiply the
configurations to evaluate (§6). The closed-set measurement is cheap and covers what actually
breaks calls.

## 10. Privacy with real applicants

**Today.** Seven-day retention, purged at startup and hourly. A candidate deletes their own
session from the page; the rows stay in backups up to three days (D34). Access codes and tokens
are stored only as hashes, the resume link is a 256-bit token valid seven days (D32), logs hold
redacted metadata and never transcripts. The model runs on a US-hosted provider (`architecture.md`,
"Who sees what"). The hosted traces carry redacted words (D42) because the data is fictional.

**What breaks first.** Redaction is patterns (emails, phones, DNI/NIE, IBAN, cards, secrets): a
name or an address said aloud is not a pattern (D42). Langfuse and the speech providers keep
data under their own retention, not our seven days. One database user owns the schema and
serves the app (D33).

**Next step.** Before the first real applicant: set `CAFE_NORTE_TRACE_CONTENT` to `off`
(runbook); sign data processing agreements with every provider and choose EU processing where
offered, including the model; separate the migration role from the runtime role and give
reviewers read access by role; a reviewed privacy notice, a retention period set by the real
purpose and a legal assessment, including whether an AI system used in recruitment falls in
the AI Act's high-risk category even when, as here, it collects facts and makes no hiring
decision.

**Trade-off.** Turning content off returns to the blind spot D42 closed. The alternative is a
reviewed redaction that also covers names, with its false negatives measured, which is slower
but is the only way to keep debuggable traces on real data.

## 11. Twilio telephony

**Today.** Voice is a Pipecat shell around our runtime (D01, D22): a transport, VAD, speech
recognition and synthesis feed `VoiceSession`, which owns every voice decision. The transport
is Daily over WebRTC; the runtime does not know that.

**What breaks first.** The read-back rule. A read-back counts as presented only when its audio
has fully played (D22, "delivered means heard"), and the page only mirrors it. In a browser a
candidate can read a summary and answer before the audio ends; KI-02 showed the cost, a lost
yes and a loop. D39 fixed it for voice alone, with no page needed: a yes over the summary earns
one offer to go over it in short parts or carry on, and a carry-on is recorded as confirmed
without full review. On a phone there is no page, so telephony inherits that fix unchanged
rather than needing one of its own.

**Next step.** A Twilio adapter for the transport only: a webhook that validates Twilio's
signature, a media-stream connection carrying 8 kHz mu-law that Pipecat's serializer converts,
phone number provisioning, and a call-end event that pauses the session the way D35 does when
a call ends. Add voicemail detection and a call-back policy for reconnects (the resume link has
no phone equivalent), a DTMF answer routed as a `ui_answer` (D38) so "press 1" resolves through
the same registry, and call-minute cost in the price table (D36).

**Trade-off.** Phone audio is narrower, so recognition of digits and "sí" worsens (§9), and the
phone read-backs for the number and the date matter more. The runtime stays unchanged, which is
the point of D01: only the edge moves.

## 12. Native speech-to-speech

**Today.** The cascade: speech recognition, our runtime with a text model, then synthesis (D01,
D22). It was chosen because every sentence passes through code we own: journaled `say` and
`aside` (D35), a runtime yes or no that does not depend on the model obeying (D35), fixed read-
backs said word for word, traces of every tool call (D36) and a priced export. Such models can
use tools; they are not excluded.

**What breaks first.** For the comparison, not for the cascade: each stage adds latency (0.4 s
for the turn end alone, D35), and a cascade hears words, not tone.

**Next step.** A measured comparison, not a switch, behind the same voice port and the same
scenarios (S01–S22): first-audio latency, interruption behaviour, tool-call reliability (the
`gpt-4o-mini` slips D35 lists are the baseline), transcript observability (can every sentence
be journaled and traced as today?), Spanish and English quality, and euros per call from the
price table. Adopt it only where it wins on tool reliability and observability as well as
latency.

**Trade-off.** A native model can sound more natural and answer faster. In exchange the
transcript becomes the model's own report of what it heard and said, and the rule that nothing
is announced before it is persisted, with D20's word-for-word read-backs, would have to be
rebuilt around it.

## What would change first

1. Measure one VM under N synthetic calls (§1): every other scaling decision depends on that
   number.
2. The uptime check, the 5xx alert and the failure-rate alerts (§3, §8): the cheapest change
   with the most effect.
3. Content off, agreements signed and roles separated (§10): the gate before any real
   applicant.
