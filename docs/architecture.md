# Architecture

Status: scaffold. The contracts below exist in code; the behaviours are specified and will be
tested when each module lands. Numbers are the defaults in `.env.example`.

## Ports and their contracts

| Port (module) | Contract |
| --- | --- |
| `Model.stream(messages, tools, *, deadline)` (`model`) | Async stream of `ModelText`, fully assembled `ToolCall`s, optional `ModelUsage`, one `ModelFinished`; malformed or late output raises `ModelError` with a stable code; provider-side tools never enabled |
| `ConversationRuntime.run_turn(TurnInput)` (`conversation`) | Async generator of `RuntimeEvent`; serialized per session; requires the current lease generation; persists before `StateUpdated`; closing it cancels work and marks the turn interrupted; duplicate `input_id` → `TurnFailed(conflict)` |
| `ToolRegistry.dispatch(ToolCall, ToolContext)` | Allowlist of nine names; arguments validated against the Pydantic model; one repair per turn; context injected by the server |
| `Retriever.retrieve(RetrievalQuery)` (`knowledge`) | Filters by `config_id` and `kb_version` before ranking; BM25 + dense fused by RRF; at most three chunks; may return none |
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

## Limits

| Limit | Default |
| --- | --- |
| Active conversation per session | 480 s, across resumes |
| Tool rounds per turn | 4 |
| Recent turns in the prompt | 20 |
| Tool arguments from the model | 16 KiB |
| SSE heartbeat while idle | 15 s |
| Clarification attempts before `unknown` | 2 (model-judged, D19) |
| Browser speech final accepted (D18 path) | confidence ≥ 0.6, ≥ 3 characters |
| Malformed-call repairs per turn | 1 |
| LLM first output | 6 s |
| External tool | 10 s |
| Text turn | 1–2000 characters |
| Voice sessions per container | 2 (Postgres-enforced) |
| Session starts per access session per hour | 3 |
| Silence | 8 s prompt, then 12 s pause |
| Database connections per container | 5 |
| Resume link validity | 7 days |
| Retention | 7 days |

## Who sees what

| Destination | Data |
| --- | --- |
| Browser | Own session only: transcript, brief, confirmations, sources, reviewer panel |
| Groq | System prompt, configuration facts, candidate state, recent turns, tool calls and results (US-hosted) |
| Deepgram / ElevenLabs / Daily | Audio and text of the voice session; no raw audio stored by us |
| Postgres | Everything the export contains; access codes and tokens only as hashes |
| Logs | Metadata keyed by session and turn; redacted free text; never transcripts |
| Langfuse | Traces with metadata; content only with `CAFE_NORTE_TRACE_CONTENT=on` and synthetic data |

## Failure contract

The spec's table (§12) is the contract; each row becomes a deterministic test with fakes.
