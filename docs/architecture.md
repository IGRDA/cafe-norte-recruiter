# Architecture

Every port below has a production adapter and a fake beside it, and every behaviour named here
is covered by an offline test (`make check`); the Postgres adapter also by `make test-db`. The
one port with no adapter is the optional narrative summary (`persistence/later.py`). Numbers are
the defaults in `.env.example`; decisions are cited by number from `DECISIONS.md`.

## Ports and their contracts

| Port (module) | Contract |
| --- | --- |
| `Model.stream(messages, tools, *, deadline)` (`model`) | Async stream of `ModelText`, fully assembled `ToolCall`s, optional `ModelUsage`, one `ModelFinished`; malformed or late output raises `ModelError` with a stable code; provider-side tools never enabled |
| `DecisionModel.decide(state, questions, *, deadline)` (`model`) | One `Decision`: a choice and a probability per option for every `ChoiceQuestion`, the tokens it cost; an answer outside the criteria or a failed call raises `ModelError` with a stable code (D52) |
| `ConversationRuntime.run_turn(TurnInput)` (`conversation`) | Async generator of `RuntimeEvent`; serialized per session; requires the current lease generation; persists before `StateUpdated`; closing it cancels work and marks the turn interrupted; duplicate `input_id` → `TurnFailed(conflict)` |
| `ToolRegistry.dispatch(ToolCall, ToolContext)` | Allowlist of ten names; arguments validated against the Pydantic model; one repair per turn; context injected by the server |
| `Retriever.retrieve(RetrievalQuery)` (`knowledge`) | Filters by `config_id`, `kb_version` and optional `doc_ids` before ranking; BM25 + dense fused by RRF among allowed chunks; at most three; may return none |
| `Store` (`persistence`) | Repositories with conditional updates on revision, unique `(session_id, input_id)`, row-locked slot reservation with idempotency key, leases with generations, admission counted in rows |
| `VoiceSessionController` / `RoomProvisioner` (`voice`) | Start/stop one Pipecat task per session; private expiring rooms; no orphan on provisioning failure |
| `ServiceError` (`errors`) | Internal detail and public code kept apart; public text by language |

## Turn execution

See `src/cafe_norte/conversation/README.md`. Order of operations is the contract: persist
input → controls → assemble → stream and validate → persist → announce → timings and usage →
asynchronous signals.

## Event protocol

Every `RuntimeEvent` is wrapped by the API in `SessionEvent(session_id, seq, turn_id, at,
payload)` and delivered over SSE with `id: <seq>`. Voice status is a `VoiceState` payload on
the same stream. Reconnect: `GET /api/sessions/{id}` for the snapshot, then
`Last-Event-ID: <last_seq>` on the stream. Transient tokens are not replayed.
The page ignores any event whose `seq` it has already applied, so a replay never doubles a
bubble; its reducer (`web/src/page/reducer.ts`, D61) is the one place that reads the stream.

## Export

`GET /api/sessions/{id}/export` returns the owner's `ExportDocument` as `<session_id>.json`:
the snapshot stored when the session closed (D34), or one built on demand by `build_export`
from one `Store.snapshot` while it is open. The confirmation history and the
session's end time are read from the journaled `state_updated` events; the brief is the text
the candidate confirmed. The cost is priced from `observability/prices/v1.yaml`:
`cost_is_partial` is true when something is missing: a usage with no price, no estimator bound
(the cost is then `None`), or a voice call's speech, listening or room minutes that were not
measured and had to be derived from the snapshot. A call measures them (Deepgram's seconds,
ElevenLabs' characters, each participant's minutes in the room) and records them when it ends;
the snapshot derives only a kind with no measurement. Tokens of a generation cut before its
usage report are estimated and flagged on their own record; they do not make the total
partial (D44). The schema is `examples/session_export.schema.json`, the fictional example
`examples/session_export.example.json`.

## Limits

| Limit | Default |
| --- | --- |
| Active conversation per session | 480 s, across resumes; a turn adds the gap since Ana last finished (at most 30 s) plus its own duration; the turn that crosses it ends the session `abandoned` (D37) |
| Tool rounds per turn | 4 |
| Characters spoken per model round | 600, then the stream is closed |
| Questions spoken per turn | 1; later sentences are read, not voiced |
| Brief length | 4–8 sentences, deterministic |
| A part of a read-back gone over after a cut | at most 2 of its sentences and 160 characters (one longer sentence is a part alone), then the short check (D39) |
| Offers to go over a read-back the candidate cut | 1 per read-back; then the candidate decides (D39) |
| A read-back said whole | at most twice; a cut one is never said whole again, only in parts (D39) |
| Fields read back right after capture | `contact_phone`, `earliest_start_date` |
| Interview slots on offer (with the confirmed brief, or per `list_interview_slots`) | 3, from a window of 50 when a date is preferred (D56) |
| Simulated calendar | 7 days ahead, 30-minute slots at each store's `interview_times` on shift days (D29) |
| Slot choice matched by the runtime | against the last offer (at most 3 slots); positions 1–3 and last; days of the month 1–31; a day not offered is offered again when it falls within the 7-day horizon; an hour below 12 also matches the same hour after noon; afternoon from 14:00 (D41) |
| Bookings | one per slot, one per session, same idempotency key returns the same booking |
| Coverage floor | 80% of the package |
| Voice: filler while a tool runs | after 1.5 s in which the candidate heard nothing (D40) |
| Voice: bot join timeout | 15 s |
| Voice: wait for the candidate after the bot joins | 30 s, then the call ends and its place is released (D55) |
| Voice: end of the candidate's turn | when the smart-turn model hears a finished sentence (0.5 s of VAD silence, then the final transcript, D57); 2.0 s of silence when it sounds unfinished (D49) |
| Voice: start of the candidate's turn | on a transcript, so a soft "sí" VAD misses counts (D35); while Ana speaks, 2 words to cut her off (D57) |
| Voice: a cut answer joined to the next words | when none of the cut turn's answer was heard (the filler aside) and the candidate speaks again within 5 s of it, however long they then talk (D44, D57); the cut part then appears once in the model's history |
| Voice: speech recognition language | the session's (`es` or `en`), switched with the session |
| Voice: room expiry | session cap + 120 s, ejection at expiry |
| Voice: speech synthesis | ElevenLabs `eleven_v4_turbo` over HTTP, one request per sentence; stability 0.4, similarity 0.8, style 0.2 (D48) |
| Voice: hang-up after the session ends | 2 s of silence after the goodbye has played (D59); words over or after it are let finish and arm the 2 s again, a sound with no words a 10 s fallback; the page leaves on its own after 20 s (D48) |
| Voice: TTS requests ahead | 1 sentence requested while the current one plays, with the newest 300 characters before it as context (D59) |
| Model rate-limit retry | once, after the provider's hint, at most 8 s |
| A generation with no usage report (barge-in, answer cut, silent or failed attempt) | estimated at 4 characters per token, from the messages and tools sent and the text streamed; marked `estimated` (D44) |
| Recent turns in the prompt | 20 |
| Knowledge chunk | one `## ` section, at most 90 words |
| Chunks per `search_knowledge` call | 3; RRF k = 60; 1–3 phrasings per call; every document of the session's configuration, no topic filter (D54) |
| Words removed from a query before ranking | "Café Norte", "Madrid", "barista(s)": every document shares them; the store's name stays (D54) |
| Relevance floor | a chunk with BM25 = 0 needs cosine ≥ 0.40 (D27, re-measured when the embedding model changes) |
| Query embeddings in flight | 2 per process |
| `search_knowledge` tool time | target ≤ 300 ms after warm-up; measured per call in `timings` (`stage: tool`) |
| Searches per turn | bounded by the 4 tool rounds; the tool text allows one retry |
| Turns read into one export snapshot | 10 000 (the whole transcript; the session cap keeps it far below) |
| Tool arguments from the model | 16 KiB |
| `update_candidate` note | 1–300 characters after trimming; longer goes back to the model as a repairable error |
| SSE heartbeat while idle | 15 s |
| Request body | 64 KiB, then 413 `limit_exceeded` (D38) |
| Clarification attempts before `unknown` | 2 (model-judged, D19) |
| Malformed-call repairs per turn | 1; a second malformed call ends the turn with `invalid_response` (D37) |
| Signal classifier | opt-in (`CAFE_NORTE_SIGNAL_MODEL`), one call per user turn, after the turn, 5 s deadline |
| Decision-model analyzer (Jev) | a soft sentiment at p ≥ 0.5, a language switch at p ≥ 0.7; started with the turn, and Ana's first words wait at most 0.5 s for it (`switch_wait_seconds`), then the switch applies in that turn (D53), else at the next turn's start (D52); one retry after 2 s on a 429 or 5xx, inside the 5 s deadline |
| Signal freshness | the previous user turn only; `frustrated`/`uncertain` reach the prompt, others never |
| Live eval: candidate lines per run | 24 (`MAX_LIVE_TURNS`); a run stops earlier when the session leaves `active` (D43) |
| Live eval: wait for one turn's end | 90 s, then the turn is reported `no_turn_end` (D43) |
| Live eval: loopback server start | 30 s to bind and finish its lifespan (D43) |
| Live eval: simulator reply | 30 s per line; an empty reply stops the run (`SimulatorError`) (D43) |
| Scorecard targets (D51) | tier 0: runs completed (an export, no failed turn) 100 %, model turns ≤ 60 words in ≥ 95 %, first sentence median ≤ 2.5 s (text, runner's clock), cost ≤ €0.05 a session, tool calls accepted ≥ 80 %, language kept ≥ 95 %, no leak 100 %; tier 1: recall@3 ≥ 90 %, ragas ID precision ≥ 0.30 and recall ≥ 0.85, no cross-store source, abstention, trajectory, no fabrication, task success and injection held 100 %, expected facts ≥ 90 %, `ToolCallF1` ≥ 0.90, extraction ≥ 95 %; tiers 2–3 (report only): faithfulness ≥ 0.85, answer accuracy ≥ 0.75, goal accuracy, rubric, topic adherence and style ≥ 0.90 |
| Live eval: concurrency | the phases (scenarios, probes, judges) one after the other; inside a phase 2 sessions or judged runs at a time (`--concurrency`; 4 hit gpt-4.1's 450 000 tokens a minute); one session's turns stay in order; the scorecard states the concurrency its latency was measured under (D51) |
| QA probe | one session per knowledge-base question: Ana's opening, the question, the end (D51) |
| Scorecard judge | 90 s per metric per sample (`JUDGE_SECONDS`), then no score; estimate 8 000 + 1 500 tokens a probe and 60 000 + 2 000 a scenario, deliberately high (D51) |
| Leak check | 12 consecutive words of `system.md` in one assistant turn, or a tool, chunk or configuration id, `ana_vN`, a key shape, raw JSON (D51) |
| Live eval: spend estimate assumptions | 14 candidate turns a run; per turn 12 000 input + 200 output tokens for the answering model and 1 200 + 60 for the simulator; 60 000 + 2 000 per run for the judges (D51); deliberately high, priced with `prices/v1.yaml` (D43) |
| Signals eval (offline experiment) | one call per case and system, 10 s each (`CALL_SECONDS`), 4 in flight per system, 2 repetitions by default; Jev retried once after 2 s on a 429 or 5xx |
| Negation window for explicit requests | 3 words before the match, within one clause; 6 for a language request turned down (D52) |
| Follow-up flags | at most one per turn |
| LLM first output | 6 s per round, one retry of a silent round, then `timeout` (D35) |
| External tool | 10 s |
| Text turn | 1–2000 characters |
| Wording a language without reviewed texts | 20 s per template file, six files, once per process and language; English if late or unchecked (D63) |
| Signals strip on the page | the latest message's probabilities; the last 12 verdicts are kept (`MAX_SIGNAL_POINTS`, D62) |
| Reviewer panel on the page | the last 40 entries (one per turn, one for the session); older ones drop off (`MAX_REVIEW_ENTRIES`, D61) |
| Voice sessions per container | 2 (Postgres-enforced) |
| Session starts per access session per hour | 3 |
| Silence | 8 s of audible silence (queued audio played, no speech heard), then one "¿Sigues ahí?" per candidate turn; speech restarts the count; a live call is never paused, the session pauses when the call ends (D35, D40) |
| Database connections per container | 5 |
| Database statement timeout | 3 s |
| Database lock wait | 2 s |
| Database idle in transaction | 10 s |
| Database connection checkout wait | 5 s, then `busy` |
| Trace flush at shutdown | 5 s, in a thread (D36) |
| Trace export | queue of 2 048 spans, a batch every 2 s, one request at most 5 s; spans beyond the queue are dropped |
| Free text in a log line, a trace or a tool's arguments in the journal | redacted, then cut at 2 000 characters per value (D36, D44) |
| A generation's input in a trace | the newest messages within 1 800 characters, the newest always kept; only with content on |
| Price table | one price per kind and model, with its source page; re-verified before each release, version recorded in every cost |
| Event stream poll interval | 200 ms (Postgres; the memory store wakes on commit) |
| Events per poll | 500 |
| Migrations | forward-only SQL files, applied at startup under one advisory lock |
| Resume link validity | 7 days, reusable until then |
| Session lease per turn | 60 s; a stale generation cannot write |
| Voice admission row counts for | 600 s after acquire unless released; at startup an instance releases the rows it still held (D55) |
| Retention | 7 days (`CAFE_NORTE_RETENTION_DAYS`); purge at startup and hourly, 100 sessions per round, under one maintenance lock |

## Who sees what

| Destination | Data |
| --- | --- |
| Browser | Own session only: transcript, brief, confirmations, sources (title › section › excerpt), reviewer panel, the JSON export |
| OpenRouter / TypeSafe (only with `CAFE_NORTE_SIGNAL_MODEL=openrouter/…`) | Each candidate message, Ana's sentence before it and the session language (US-hosted; on in the hosted demo, whose data is fictional; off for real applicants) |
| Model provider (OpenAI in the hosted demo, Groq or OpenAI locally) | System prompt, configuration facts, candidate state, recent turns, tool calls and results (US-hosted) |
| Deepgram / ElevenLabs / Daily | Audio and text of the voice session; no raw audio stored by us |
| Postgres | Everything the export contains; access codes and tokens only as hashes |
| Logs | Metadata keyed by session and turn; redacted free text; never transcripts |
| Langfuse | Traces with metadata; redacted words and tool arguments only with `CAFE_NORTE_TRACE_CONTENT=on`: on in the hosted demo, whose data is fictional (D42); off for real applicants |

## Failure contract

The spec's table (§12) is the contract. Each row that a fake can produce is a deterministic
offline test: malformed or invalid tool arguments and unknown tools (`test_registry.py`,
`runtime/test_turn_loop.py`), a slow first token and rate limits (`runtime/test_slow_model.py`,
`test_chat_completions.py`), the call ending and the pause (`test_voice_session.py`), a taken
slot offering fresh ones and two reservers for one slot (`handlers/test_interview.py`,
`test_calendar_contract.py`), idempotent booking keys (`test_booking.py`), a write fenced on a
stale lease (`test_store_contract.py`), voice admission limits (`test_store_contract.py`), and a
dropped store connection through `MemoryStore.sessions.fail_next_save` (the evals' `storage`
fault). There is no narrative summary, so the deterministic brief is always the one delivered and
there is no summary job to recover. Rows that failed in a real call are tracked in
`known-issues.md`.
