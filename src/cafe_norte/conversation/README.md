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
| `handlers.py` | `all_handlers()`: update, search knowledge, list interview slots, present (read-backs, the brief, a slot), confirm field/brief, reserve interview, request human follow-up, end session. Each reads state, lets the domain decide, commits, announces; `model_text` is the model's next step in one sentence |
| `brief.py` | The deterministic brief, the phone/date read-backs, the slot offer and the slot read-back, filled from `prompts/brief.md`; spoken verbatim by the runtime (D20) |
| `prompt.py` | System message from the versioned prompt plus session facts as JSON; history window; sentence splitting |
| `runtime.py` | `Runtime`: one turn at a time per session, journal-before-yield, streamed sentences, bounded tool loop (four rounds), first-output and tool deadlines. Cancellation and repair counting: later stages |
| `prompts/` | Versioned prompt files and `PROMPT_VERSION` |
| `signals.py` | Synchronous stop/human/language fast path and the asynchronous sentiment classifier port |

## Questions and the knowledge base

`search_knowledge(question, queries, topic)`: the model keeps the candidate's words in
`question`, writes one to three self-contained Spanish `queries` (an English question is
reformulated here; a second phrasing for vague questions) and names a `topic`. The handler
applies the structured half (configuration, KB version, topic → documents, `faq` always
allowed) before ranking, returns at most three snippets as numbered reference material with
the rules and the next step, and emits `SourcesShown`. The model may search once more in the
same turn; the four-round limit bounds it. A chunk with no query word and a cosine below the
floor is dropped (D27); beyond that, abstention is the prompt's job. When nothing answers,
Ana offers human follow-up and `request_human_followup(reason)` saves one review flag. After
the confirmed brief the next step is to invite questions, then the interview.

## The interview

After the confirmed brief and the questions, Ana asks about an interview. A yes is
`list_interview_slots(evidence_text)`: the handler saves the candidate's words as the explicit
intent to schedule, reads up to three future free slots of this store (preferring a stated
date), and the runtime speaks the offer; the model gets the slot ids in the same order. The
candidate's choice is `present_confirmation(target=slot, slot_id)`: a read-back bound to the
current brief revision, spoken by the runtime and marked delivered like the brief. The yes to
it is `reserve_interview(slot_id)`: the domain resolves the confirmation and checks the five
conditions, then the calendar row and the session are written in one transaction, and only
the committed `StateUpdated` carries the booking (D29). A taken slot comes back as a refusal
that asks for fresh slots; a second call for the same confirmation is refused as already
answered. After booking the next step is `end_session`, which yields `completed / reserved`.

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
