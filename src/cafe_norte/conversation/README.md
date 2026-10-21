# `conversation`: one runtime, two channels

`ConversationRuntime.run_turn` is the only way a user turn becomes assistant output;
`open_session` journals Ana's fixed opening sentence before any input (D19). Voice and
text are adapters that feed it finalized text and consume its events; neither has an agent of
its own.

| File | Contents |
| --- | --- |
| `contracts.py` | `TurnInput`, the `RuntimeEvent` union, `ToolContext`, `ToolOutcome`, ports `ConversationRuntime`, `ToolHandler`, `SignalAnalyzer` |
| `tools.py` | The allowlist: one Pydantic argument model per tool and the `ToolSchema` table derived from them |
| `registry.py` | `ToolRegistry`: name to handler, argument validation; only tools with a handler are advertised |
| `handlers.py` | `all_handlers()`: update, search knowledge, present (read-backs and the brief), confirm field/brief, end session. Each reads state, lets the domain decide, commits, announces; `model_text` is the model's next step in one sentence |
| `brief.py` | The deterministic brief and the phone/date read-backs, filled from `prompts/brief.md`; spoken verbatim by the runtime (D20) |
| `prompt.py` | System message from the versioned prompt plus session facts as JSON; history window; sentence splitting |
| `runtime.py` | `Runtime`: one turn at a time per session, journal-before-yield, streamed sentences, bounded tool loop (four rounds), first-output and tool deadlines. Cancellation and repair counting: later stages |
| `prompts/` | Versioned prompt files and `PROMPT_VERSION` |
| `signals.py` | Synchronous stop/human/language fast path and the asynchronous sentiment classifier port |

## Questions and the knowledge base

`search_knowledge(question, query, topic)`: the model keeps the candidate's words in
`question`, writes one self-contained Spanish `query` (an English question is reformulated
here) and names a `topic`. The handler applies the structured half (configuration, KB version,
topic → documents, `faq` always allowed) before ranking, returns at most three snippets as
numbered reference material with the rules and the next step, and emits `SourcesShown`.
The model may search once more in the same turn; the four-round limit bounds it. Abstention
is the prompt's job in this stage: no relevance floor yet (D26). After the confirmed brief the
next step is to invite questions, then the interview.

## Turn execution

1. Accept one finalized `TurnInput` with a unique `input_id`; persist the user turn.
2. Apply explicit stop, language switch and human-request controls; cancel stale output.
3. Build messages from: system prompt, configuration facts, validated candidate state, pending
   confirmation, unfinished fields, recent turns.
4. Stream the model. Each `ToolCall` is validated by `ToolRegistry`, then by the domain, then
   executed through the repositories inside one transaction.
5. Persist mutations and tool results, then emit `StateUpdated`; only then does Ana announce.
6. Stream `AssistantText` sentence by sentence. Record what was generated and, later, what was
   delivered.
7. Persist timings and usage. Hand nonessential analysis to `SignalAnalyzer` asynchronously.

Bounds: four tool rounds per turn, one malformed-call repair, six seconds to first model output,
ten seconds per tool, the session's remaining active seconds as the hard deadline.
