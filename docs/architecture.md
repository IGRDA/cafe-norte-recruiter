# Architecture

Status: scaffold. The contracts below exist in code; the behaviours are specified and will be
tested when each module lands. Numbers are the defaults in `.env.example`.

## Ports and their contracts

| Port (module) | Contract |
| --- | --- |
| `Model.stream(messages, tools, *, deadline)` (`model`) | Async stream of `ModelText`, fully assembled `ToolCall`s, optional `ModelUsage`, one `ModelFinished`; malformed or late output raises `ModelError` with a stable code; provider-side tools never enabled |
| `ConversationRuntime.run_turn(TurnInput)` (`conversation`) | Async generator of `RuntimeEvent`; serialized per session; requires the current lease generation; persists before `StateUpdated`; closing it cancels work and marks the turn interrupted; duplicate `input_id` → `TurnFailed(conflict)` |
| `ToolRegistry.dispatch(ToolCall, ToolContext)` | Allowlist of nine names; arguments validated against the Pydantic model; one repair per turn; context injected by the server |
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

## Export

`GET /api/sessions/{id}/export` returns the owner's `ExportDocument` as `<session_id>.json`:
the snapshot stored when the session closed (D34), or one built on demand by `build_export`
from one `Store.snapshot` while it is open. The confirmation history and the
session's end time are read from the journaled `state_updated` events; the brief is the text
the candidate confirmed; the cost estimate stays `None` (`cost_is_partial: true`) until prices
are recorded. The schema is `examples/session_export.schema.json`, the fictional example
`examples/session_export.example.json`.

## Limits

| Limit | Default |
| --- | --- |
| Active conversation per session | 480 s, across resumes; a turn adds the gap since Ana last finished (at most 30 s) plus its own duration; the turn that crosses it ends the session `abandoned` (D37) |
| Tool rounds per turn | 4 |
| Characters spoken per model round | 600, then the stream is closed |
| Questions spoken per turn | 1; later sentences are read, not voiced |
| Brief length | 4–8 sentences, deterministic |
| Fields read back right after capture | `contact_phone`, `earliest_start_date` |
| Interview slots offered per `list_interview_slots` | 3, from a window of 50 when a date is preferred |
| Simulated calendar | 7 days ahead, 30-minute slots at each store's `interview_times` on shift days (D29) |
| Bookings | one per slot, one per session, same idempotency key returns the same booking |
| Coverage floor | 80% of the package |
| Voice: filler after a tool runs | 1.5 s |
| Voice: bot join timeout | 15 s |
| Voice: user speech timeout before a turn ends | 1.0 s; a transcript can start a turn when VAD misses it (D35) |
| Voice: speech recognition language | the session's (`es` or `en`), switched with the session |
| Voice: room expiry | session cap + 120 s, ejection at expiry |
| Model rate-limit retry | once, after the provider's hint, at most 8 s |
| Recent turns in the prompt | 20 |
| Knowledge chunk | one `## ` section, at most 90 words |
| Chunks per `search_knowledge` call | 3; RRF k = 60; 1–3 phrasings per call |
| Relevance floor | a chunk with BM25 = 0 needs cosine ≥ 0.40 (D27, re-measured when the embedding model changes) |
| Query embeddings in flight | 2 per process |
| `search_knowledge` tool time | target ≤ 300 ms after warm-up; measured per call in `timings` (`stage: tool`) |
| Searches per turn | bounded by the 4 tool rounds; the tool text allows one retry |
| Turns read into one export snapshot | 10 000 (the whole transcript; the session cap keeps it far below) |
| Tool arguments from the model | 16 KiB |
| SSE heartbeat while idle | 15 s |
| Clarification attempts before `unknown` | 2 (model-judged, D19) |
| Browser speech final accepted (D18 path) | confidence ≥ 0.4, ≥ 2 characters |
| Malformed-call repairs per turn | 1; a second malformed call ends the turn with `invalid_response` (D37) |
| Signal classifier | opt-in (`CAFE_NORTE_SIGNAL_MODEL`), one call per user turn, after the turn, 5 s deadline |
| Signal freshness | the previous user turn only; `frustrated`/`uncertain` reach the prompt, others never |
| Negation window for explicit requests | 3 words before the match, within one clause |
| Follow-up flags | at most one per turn |
| LLM first output | 6 s per round, one retry of a silent round, then `timeout` (D35) |
| External tool | 10 s |
| Text turn | 1–2000 characters |
| Voice sessions per container | 2 (Postgres-enforced) |
| Session starts per access session per hour | 3 |
| Silence | 8 s, then one "¿Sigues ahí?"; a live call is never paused, the session pauses when the call ends (D35) |
| Database connections per container | 5 |
| Database statement timeout | 3 s |
| Database lock wait | 2 s |
| Database idle in transaction | 10 s |
| Database connection checkout wait | 5 s, then `busy` |
| Event stream poll interval | 200 ms (Postgres; the memory store wakes on commit) |
| Events per poll | 500 |
| Migrations | forward-only SQL files, applied at startup under one advisory lock |
| Resume link validity | 7 days, reusable until then |
| Session lease per turn | 60 s; a stale generation cannot write |
| Voice admission row counts for | 600 s after acquire unless released |
| Retention | 7 days (`CAFE_NORTE_RETENTION_DAYS`); purge at startup and hourly, 100 sessions per round, under one maintenance lock |

## Who sees what

| Destination | Data |
| --- | --- |
| Browser | Own session only: transcript, brief, confirmations, sources (title › section › excerpt), reviewer panel, the JSON export |
| Groq | System prompt, configuration facts, candidate state, recent turns, tool calls and results (US-hosted) |
| Deepgram / ElevenLabs / Daily | Audio and text of the voice session; no raw audio stored by us |
| Postgres | Everything the export contains; access codes and tokens only as hashes |
| Logs | Metadata keyed by session and turn; redacted free text; never transcripts |
| Langfuse | Traces with metadata; content only with `CAFE_NORTE_TRACE_CONTENT=on` and synthetic data |

## Failure contract

The spec's table (§12) is the contract; each row becomes a deterministic test with fakes.
