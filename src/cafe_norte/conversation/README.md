# `conversation`: one runtime, two channels

`ConversationRuntime.run_turn` is the only way a user turn becomes assistant output;
`open_session` journals Ana's fixed opening sentence before any input (D19). Voice and
text are adapters that feed it finalized text and consume its events; neither has an agent of
its own.

| File | Contents |
| --- | --- |
| `contracts.py` | `TurnInput` (and `UiAnswer`, the page's Sí / No on a read-back, D38), the `RuntimeEvent` union (`SignalRecorded` included; `ToolStarted` carries the call's arguments, redacted, D44), `ToolContext`, `ToolOutcome` (`malformed` spends the repair budget; `idle` marks a call that changed nothing, D44), ports `ConversationRuntime`, `ToolHandler`, `SignalAnalyzer` (returns a `SignalAnalysis`: the signal or none, and the tokens the call cost, D44) |
| `tools.py` | The allowlist: one Pydantic argument model per tool and the `ToolSchema` table derived from them |
| `registry.py` | `ToolRegistry`: name to handler, argument validation; only tools with a handler are advertised |
| `handlers.py` | `all_handlers()`: update, search knowledge, list interview slots, present (read-backs, the brief, a slot), confirm field/brief, reserve interview, review a cut read-back (`review_readback`: the one offer, each part, and a carry-on confirmed through the read-back's own handler in the same call, D39), request human follow-up, end session. A cut read-back presented again starts with its first part instead of being said whole again. `update_candidate` keeps as evidence the candidate's own message that holds the cited words and refuses words they never said (`evidence_not_said`, D46). Each reads state, lets the domain decide, commits, announces; `model_text` is the model's next step in one sentence |
| `brief.py` | The deterministic brief, the phone/date read-backs, the slot offer and the slot read-back, filled from `prompts/brief.<lang>.md` in the session language; spoken verbatim by the runtime (D20). A requested follow-up adds one sentence |
| `readback.py` | Going over a read-back the candidate cut (D39): `review_parts` slices it into parts of at most two sentences and 160 characters, each ending with `review.check`; `current_saying` is the part under review or the whole text; `target_call` is the read-back's own tool for an answer (`CONFIRM_TOOL`); `answer_call` routes a plain yes, no or carry-on by the review stage (the whole table in one function) |
| `prompt.py` | System message from the versioned prompt plus session facts as JSON (`PromptHints`: this turn's explicit requests and the previous turn's fresh sentiment); history window; sentence splitting (`split_sentences` for a stream, `sentences` for a whole text); `tool_message` (a tool result plus what was already said this turn); `conversation_tail` (what a generation's trace keeps of the conversation) |
| `slot_answer.py` | The candidate's answer to the slot offer (D41), pure: `slot_answer` returns the tool to run (read the slot back, reserve the one read back and heard on a yes, offer again for a named day), a `Shortlist` to ask about, or nothing; `open_offer`, `heard_read_back_of` |
| `runtime.py` | `Runtime`: one turn at a time per session, journal-before-yield, streamed sentences, bounded tool loop (four rounds; a round whose calls changed nothing ends it once the question was said, and a tool whose call changed nothing is not offered again that turn, D44), first-output and tool deadlines, the explicit-request fast path (language switch, D28; human request, D30; a plain yes, no or carry-on to the pending read-back, D35, routed by `readback.answer_call`: one heard to the end is answered, one the candidate cut goes to `review_readback`, D39; a button answer is routed the same way and no longer counts as hearing it; the candidate's choice of slot, decided by `slot_answer`, D41; a goodbye or thanks once the interview is booked ends the session with the fixed goodbye and no model round, D46), one retry of a silent model round, a generation that ends with no usage report estimated at 4 characters per token (D44), a paused session made active by its next turn, `say` and `aside` for sentences the system speaks (D35), `record_usage` for usage measured outside a turn (a call's speech providers; an ended session's export is stored again, D44), signal analysis after the turn (`settle` waits for it), one malformed-call repair per turn, active seconds accumulated per turn with the 480 s cap, a cancelled or closed turn journaled as interrupted (D37), structured events through the `Telemetry` port (`turn_failed`, `model_round`, `model_round_silent`, `answer_cut`: metadata only), and one trace per turn: `handle-candidate-turn`, then `write-user-turn`, `invoke-agent`, `step` (one per model round), `chat` (the generation, with tokens), one span per tool call (`retriever` for `search_knowledge`) and `write-assistant-turn`. Parents are passed explicitly. |
| `prompts/` | Versioned prompt files and `PROMPT_VERSION` |
| `signals.py` | `explicit_controls` (pure patterns for stop, human and language requests, es/en), `requested_language`, `answer_to_readback` (a whole-utterance yes or no), `is_farewell` (a goodbye or thanks with nothing left to do, D46), `ModelSignalAnalyzer` (the asynchronous classifier adapter; its tokens are recorded under the turn it classified, D44), `DecisionSignalAnalyzer` (the same port over a `DecisionModel`, Jev: the two questions of `prompts/signal_questions.yaml`, a soft sentiment at p ≥ 0.5, a language switch at p ≥ 0.7, D52), `fresh_sentiment` and `fresh_switch` |

## Questions and the knowledge base

`search_knowledge(question, queries)`: the model keeps the candidate's words in
`question` and writes one to three self-contained Spanish `queries` (an English question is
reformulated here; a second phrasing for vague questions). The handler applies the structured
half (the configuration's documents and KB version; no topic, D53) before ranking, returns at most three snippets as numbered reference material with
the rules and the next step, and emits `SourcesShown`. The model may search once more in the
same turn; the four-round limit bounds it. A chunk with no query word and a cosine below the
floor is dropped (D27); beyond that, abstention is the prompt's job. When nothing answers,
Ana offers human follow-up and `request_human_followup(reason)` saves one review flag. After
the confirmed brief the next step is to invite questions, then the interview.

## The interview

After the confirmed brief and the questions, Ana asks about an interview. A yes is
`list_interview_slots(evidence_text)`: the handler saves the candidate's words as the explicit
intent to schedule, reads up to three future free slots of this store (preferring a stated
date), and the runtime speaks the offer; the model gets the slot ids in the same order, and
the session keeps them (`slot_offer`). The runtime matches the candidate's answer against that
offer first (D41): one slot that fits is read back, several are a shortlist the model asks
about, none is a new offer for the day named. The model's own call stays the fallback. The
candidate's choice is `present_confirmation(target=slot, slot_id)`: a read-back bound to the
current brief revision, spoken by the runtime and marked delivered like the brief. The yes to
it is `reserve_interview(slot_id)`: the domain resolves the confirmation and checks the five
conditions, then the calendar row and the session are written in one transaction, and only
the committed `StateUpdated` carries the booking (D29). A taken slot comes back as a refusal
that asks for fresh slots; a second call for the same confirmation is refused as already
answered. After booking the next step is `end_session`, which yields `completed / reserved`.

## Turn execution

1. Accept one finalized `TurnInput` with a unique `input_id`; persist the user turn (a button answer has no words: the language's `ui` label is recorded).
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

## Explicit requests and signals (D28, D30, D52)

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

With `CAFE_NORTE_SIGNAL_MODEL=openrouter/typesafe/jev-1.14` the analyzer is a decision model
(D52): one call reads the session language, what Ana said last and the message, and answers
the sentiment and whether to keep or switch the language, with probabilities. A switch it
reads (p ≥ 0.7, "my Spanish is not very good") applies at the start of the next turn the way
an explicit request does: saved with the user turn, before the model; an explicit request in
that turn wins, and a verdict from an older turn switches nothing. The analyzer runs beside
the turn: it adds no latency, and one candidate turn passes in the old language.

Bounds: four tool rounds per turn, one malformed-call repair (a second ends the turn with
`invalid_response`), six seconds to first model output, ten seconds per tool, 480 active seconds
per session across resumes (the remaining seconds are the model's hard deadline).
