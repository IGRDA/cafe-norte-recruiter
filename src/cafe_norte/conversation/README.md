# `conversation`: one runtime, two channels

`ConversationRuntime.run_turn` is the only way a user turn becomes assistant output;
`open_session` journals Ana's fixed opening sentence before any input (D19). Voice and
text are adapters that feed it finalized text and consume its events; neither has an agent of
its own.

| File | Contents |
| --- | --- |
| `contracts.py` | `TurnInput`, the `RuntimeEvent` union (`SignalRecorded` included), `ToolContext`, `ToolOutcome` (`malformed` spends the repair budget), ports `ConversationRuntime`, `ToolHandler`, `SignalAnalyzer` |
| `tools.py` | The allowlist: one Pydantic argument model per tool and the `ToolSchema` table derived from them |
| `registry.py` | `ToolRegistry`: name to handler, argument validation; only tools with a handler are advertised |
| `handlers.py` | `all_handlers()`: update, search knowledge, list interview slots, present (read-backs, the brief, a slot), confirm field/brief, reserve interview, request human follow-up, end session. Each reads state, lets the domain decide, commits, announces; `model_text` is the model's next step in one sentence |
| `brief.py` | The deterministic brief, the phone/date read-backs, the slot offer and the slot read-back, filled from `prompts/brief.<lang>.md` in the session language; spoken verbatim by the runtime (D20). A requested follow-up adds one sentence |
| `prompt.py` | System message from the versioned prompt plus session facts as JSON (`PromptHints`: this turn's explicit requests and the previous turn's fresh sentiment); history window; sentence splitting |
| `runtime.py` | `Runtime`: one turn at a time per session, journal-before-yield, streamed sentences, bounded tool loop (four rounds), first-output and tool deadlines, the explicit-request fast path (language switch, D28; human request, D30; a plain yes or no to a heard read-back, D35), one retry of a silent model round, a paused session made active by its next turn, `say` and `aside` for sentences the system speaks (D35), signal analysis after the turn (`settle` waits for it), one malformed-call repair per turn, active seconds accumulated per turn with the 480 s cap, and a cancelled or closed turn journaled as interrupted (D37) |
| `prompts/` | Versioned prompt files and `PROMPT_VERSION` |
| `signals.py` | `explicit_controls` (pure patterns for stop, human and language requests, es/en), `requested_language`, `answer_to_readback` (a whole-utterance yes or no), `ModelSignalAnalyzer` (the asynchronous classifier adapter) and `fresh_sentiment` |

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
2. Apply explicit controls: a language request is saved with the user turn, before the
   model is called (D28). Stop and human requests and stale-output cancellation follow.
3. Build messages from: system prompt, configuration facts, validated candidate state, pending
   confirmation, unfinished fields, recent turns.
4. Stream the model. Each `ToolCall` is validated by `ToolRegistry`, then by the domain, then
   executed through the repositories inside one transaction.
5. Persist mutations and tool results, then emit `StateUpdated`; only then does Ana announce.
6. Stream `AssistantText` sentence by sentence. Record what was generated and, later, what was
   delivered.
7. In one transaction persist the assistant turn, timings, usage and the turn's active seconds
   (the gap since Ana last finished, at most 30 s, plus the turn itself). Past the cap the same
   transaction abandons the session: `StateUpdated`, then the fixed `time_cap` goodbye (D37).
   Hand nonessential analysis to `SignalAnalyzer` asynchronously.

A turn closed or cancelled mid-stream (barge-in, hang-up) takes the same exit: the model
stream is closed, what was said is stored as an interrupted assistant turn, `TurnFinished` is
journaled with `interrupted=True` and the lease is released.

## Explicit requests and signals (D28)

Step 2 is `explicit_controls(text)`: anchored phrases per clause, a negation in the
three words before a match cancels it. A human request saves a `human_followup` flag
(`domain/review.py`), emits `StateUpdated`, then says `prompts/controls.<lang>.md` word for word; the
model still runs (the sentence may carry a fact) but voices nothing more. A stop request is a
hint: `explicit_requests: ["stop"]` in the session facts, and the model calls `end_session`.

When `CAFE_NORTE_SIGNAL_MODEL` is set, every finished user turn is classified in a background
task. A verdict needs the candidate's own words as evidence or it is dropped; it is journaled
as `SignalRecorded` (SSE, reviewer panel, export) and kept in memory. The next turn's prompt
gets `candidate_sentiment` only when the verdict is `frustrated` or `uncertain` and comes from
the immediately previous user turn; a late or older verdict never reaches a prompt.

Bounds: four tool rounds per turn, one malformed-call repair (a second ends the turn with
`invalid_response`), six seconds to first model output, ten seconds per tool, 480 active seconds
per session across resumes (the remaining seconds are the model's hard deadline).
