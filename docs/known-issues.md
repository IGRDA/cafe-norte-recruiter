# Known issues

Problems seen in real calls, documented and reproduced where possible. A fixed entry stays,
with the decision or commit that fixed it, so the evidence trail is complete. Each entry says what happened, the evidence, the cause, how to reproduce it and
the fix proposed. A reproduction in `tests/component/test_known_issues.py` is a strict `xfail`: it fails
today, and the commit that fixes the issue removes the marker.

Source of the entries below: the second hosted voice call of 21 October 2026, after the D35
fixes were deployed (session `13c11b937f0a4ab089eadd32d21796e5`, 16:06–16:11 UTC, gpt-4o-mini,
Cloud SQL). Evidence is the session's `events` journal (`seq`) and the app container's logs.

**What D35 fixed and this call confirmed:** a bare "Sí" started its own turn; the date was
confirmed by "Correcto." through the runtime (seq 66, `confirm_field` with no model round);
"Cuarenta horas más." saved 40 with its evidence; the location question was searched and
answered with its source (seq 94–99); "¿Sigues ahí?" and the apology appear in the transcript;
the session never paused during the call; no model round timed out.

| Id | Problem | Severity | Reproduced by | Belongs with |
|---|---|---|---|---|
| KI-01 | "Está todo bien" is not taken as a yes | High | `test_ki01_…` | **fixed (D39)** |
| KI-02 | A yes to the summary on screen is lost when its audio was cut; the summary loops | High | `test_ki02_…`, S21, S22, the read-back matrix | **fixed (D39)** |
| KI-03 | "¿Sigues ahí?" while the candidate is speaking | High | `test_ki03_…` | **fixed (D40)** |
| KI-04 | "¿Sigues ahí?" twice after a failed turn | Medium | `test_ki04_…` | **fixed (D40)** |
| KI-05 | System sentences are said ahead of the audio still playing | Medium | `test_ki05_…` | **fixed (D40)** |
| KI-06 | Choosing an interview slot loops and never books | High | `test_ki06_…`, S20 | **fixed (D41)** |
| KI-07 | A hesitation splits the answer and the first part is lost silently | Medium | `test_ki07_…` | **fixed (D44)** |
| KI-08 | Wasted model rounds add latency | Low | `test_ki08_…` (two) | **fixed (D44)** |
| KI-09 | A mention or a refusal of a language switches it; a frustrated request does not | Medium | `test_ki09_…` (four), the signals suite | **fixed (D52)** |
| KI-10 | No interview time is ever said: the model promises them and calls no tool | High | S28 | **fixed (D56)** |
| KI-11 | An invented slot id makes the whole list be said again, up to four times | High | S29, `test_a_wrong_choice_…` | **fixed (D56)** |
| KI-12 | Ana cuts the candidate off when they take a breath mid-sentence | High | `test_a_finished_sentence_…`, `test_a_long_continuation_…`, `test_a_fragment_joined_…` | **fixed (D57)**, to confirm by voice |
| KI-13 | A complaint ("estoy mosqueado… mala reputación") gets the next field question | High | `test_frustration_read_before_…` | **fixed (D58)** |
| KI-14 | "Sí, anótalo" to a follow-up offer becomes a note nobody reads | High | S30, `test_a_note_tells_the_model_…` | **fixed (D58)** |
| KI-15 | "Guardo que…" said in a turn that saved nothing | High | `claims_saved_without_save` in every scenario | **fixed (D58)** |
| KI-16 | "Enero del año que viene" saved and read back as 1 January | Medium | S31, `test_a_start_day_the_candidate_did_not_say_…` | **fixed (D58)** |
| KI-17 | A confirmed start date is read back a second time | Medium | `test_a_confirmed_field_is_not_read_back_again` | **fixed (D58)** |
| KI-18 | A question during the read-back review is taken as a yes; the answer comes three turns late | Medium | `test_a_question_during_the_review_…` | **fixed (D58)** |
| KI-19 | "Muchas gracias" inside a longer sentence ends the call at once | High | `test_thanks_beside_other_words_…` | **fixed (D59)** |
| KI-20 | A question in the closing line is answered with the goodbye | High | S32, `test_a_question_in_the_closing_line_…` | **fixed (D59)** |

## KI-01 · "Está todo bien" is not taken as a yes

- **What happened.** "Sí, está todo bien." (seq 87), "Está todo bien." (116) and "Está todo bien.
  Todo correcto." (131) were left to the model, which did not call `confirm_brief`.
- **Cause.** `signals.answer_to_readback` matches whole phrases; "está todo bien" has "todo"
  between "está" and "bien", so no listed phrase covers it and the leftover word makes it "not
  plain".
- **Fix.** Add "está todo bien", "todo bien", "está bien todo", "todo está bien" (and the
  English "all good", "that's all right") to the affirmations; consider word-set matching for
  the "todo / bien / correcto" family.
- **Fixed** (commit `bdc588d`, merged in PR #26). `signals.answer_to_readback` takes a yes as an
  answer made only of yes-words and fillers, in any order, with at least one core yes-word and
  no negation; "todo" or "está" alone only support a core word. "Está todo bien", "Todo bien",
  "Está bien todo", "All good" and "That is all right" are a plain yes; `test_ki01_…` passes
  with no marker, and a no still wins first. Since D39 a
  carry-on ("sigue", "adelante") is its own answer.

## KI-02 · A yes to the summary on screen is lost when its audio was cut

- **What happened.** The summary is eight sentences, about 12 s of audio, and appears on the
  page at once. Iñaki read it and answered at 16:08:06, 10.8 s into the audio, before "¿Es
  todo correcto?" played. The aggregator's interruption (16:08:06.1) cut it, so the read-back
  was not heard (D22) and the yes could not confirm it. The model then re-presented it
  (D35: an unheard read-back is read again), Iñaki answered over it again 3 s in (16:08:49),
  and the third time the turn hit its round limit (seq 149, `limit_exceeded`). Only the yes at
  16:09:28, after the audio had finished, confirmed it (seq 160).
- **Cause.** "Delivered means heard" (D22) assumes voice only. With the page showing the text,
  the candidate answers what they read; a re-read has the same length, so it is cut the same
  way, without end.
- **Reproduce.** `test_ki02_…`: voice channel, summary presented, playback never completes, a
  plain "Sí." next: the read-back stays `pending`.
- **Fix (decide first).** Speak a short summary ("Te lo he puesto en pantalla, ¿está todo
  bien?") and show the full one; or count a read-back as presented once its last sentence was
  shown on a connected page, keeping "heard" for voice-only; and re-read at most once.
- **Fixed (D39).** Decided with the owner: voice only, the page never counts as hearing. The
  yes over the summary earns one offer, in the model's words, to go over it or carry on.
  "Sigue." (or a plain "no" to the offer) confirms it, recorded in the export as `waived`;
  "sí" goes over it in short parts, each with "¿Está bien?", and the yes to the last one
  confirms it as `reviewed`. A cut read-back is never said whole again. `test_ki02_…` replays
  the call; S21, S22 and `tests/component/test_readback_matrix.py` cover every kind and cut.

## KI-03 · "¿Sigues ahí?" while the candidate is speaking

- **What happened.** At 16:06:46.7 the aggregator logged "User started speaking (strategy:
  TranscriptionUserTurnStartStrategy)"; "¿Sigues ahí?" was generated at 16:06:50.1, over the
  answer. Same at 16:09:26 (speech) and 16:09:28 (prompt).
- **Cause.** D35 resets the silence clock on raw transcripts in `InboundBridge`, but Pipecat's
  `LLMUserAggregator` consumes every transcript frame and never pushes it downstream, so the
  bridge never sees one (the unit test fed frames straight to the bridge). The start of speech
  does reach the session as an interruption, and `VoiceSession.interrupted()` does not cancel
  the clock.
- **Reproduce.** `test_ki03_…`: the clock armed, then `interrupted()`; the prompt still plays.
- **Fix.** Cancel the clock in `interrupted()`; move the transcript tap before the aggregator
  (a tiny processor between STT and the aggregator) and test it with the real aggregator in
  `run_test`.
- **Fixed (D40).** `SpeechTap` sits between STT and the aggregator, tested through the real
  aggregator (`user_side`); an interruption and any transcript restart the countdown, and once
  the prompt was said speech does not earn another.

## KI-04 · "¿Sigues ahí?" twice after a failed turn

- **What happened.** The apology at 16:09:04, "¿Sigues ahí?" at 16:09:12 and again at 16:09:28.
- **Cause.** The failure path starts the silence clock at once; when the failed turn's queued
  sentences finish playing, `played_one` acknowledges the turn and starts the clock again.
- **Reproduce.** `test_ki04_…`.
- **Fix.** One clock per listening period: the failure path acknowledges the turn first, or
  `_maybe_acknowledge` does not re-arm a clock that is already running.
- **Fixed (D40).** Listening starts in one place, `VoiceSession._drained`, and the one prompt
  is earned again only by the candidate's next turn.

## KI-05 · System sentences are said ahead of the audio still playing

- **What happened.** The third summary was still playing until 16:09:23. The apology was
  journaled at 16:09:04 and "¿Sigues ahí?" at 16:09:12: the transcript showed them before they
  could be heard, and the audio played them right after the summary, back to back. Iñaki: "at
  the same time gives the message ¿Sigues ahí? and reads it after".
- **Cause.** `VoiceSession` speaks the apology and starts the silence clock as soon as the turn
  fails, without waiting for the sentences already sent to TTS.
- **Reproduce.** `test_ki05_…`: a failed turn with two sentences unplayed; the apology is said.
- **Fix.** Wait for the ledger to drain (or cut the queued audio first) before a system
  sentence; start the silence clock only after the last sentence played.
- **Fixed (D40).** The queued sentences play to the end; then the apology is journaled and
  spoken, and the clock starts once it has played. The filler follows the same rule.

## KI-06 · Choosing an interview slot loops and never books

- **What happened.** Three slots were offered (seq 165). "El viernes." made the model call
  `list_interview_slots` again (two Friday slots, seq 172); "El viernes." again got a question
  in plain text with no `present_confirmation` (177); "Exacto, sí." made it call
  `reserve_interview` with no slot read-back pending (`confirmation_mismatch`, 181), then
  `present_confirmation` for a slot id that does not exist (`slot_unavailable`, 183), then the
  full list again. The same loop three more times; nothing booked.
- **Cause.** The model must copy a slot id from the tool text into `present_confirmation`;
  gpt-4o-mini did not, or mangled it. The journal does not record tool arguments, so the id it
  sent cannot be checked (observability gap; hosted traces carry tool arguments since D42).
- **Reproduce (manual).** Hosted or `make voice-smoke`: confirm the summary, ask for an
  interview, answer the offer with a day only ("el viernes"), then "sí".
- **Fix.** Resolve the choice in the runtime like a yes/no: match "el primero", "el viernes",
  "a las diez y media", "el 23" against the slots just offered and present the read-back
  without the model; journal tool arguments (the observability stream).
- **Fixed (D41).** The runtime matches the answer against the offer
  (`domain/slot_choice.py`), reads one fitting slot back, keeps a shortlist and lets the model
  ask when several fit, offers again when none does, and books a yes that restates the slot.
  `test_ki06_…` and scenario S20 replay the call. Tool arguments are journaled since D44
  (`ToolStarted.arguments`, redacted), so the export and the reviewer panel show them.

## KI-07 · A hesitation splits the answer and the first part is lost silently

- **What happened.** "El lunes," (seq 53) and "uno, de, dos de noviembre." (54) became two
  turns 4 s apart; the first was cancelled by the second without a `turn_finished` or
  `turn_failed`, and the page showed "…" for it.
- **Cause.** A pause longer than the 1.0 s speech timeout ends the turn; a new turn interrupts
  the running one; cancellation is not journaled (runtime robustness item).
- **Fix.** Journal the cancelled turn as interrupted (runtime robustness stream); consider a
  longer timeout after a question that expects a date or a number, or Pipecat's smart-turn.
- **Fixed (D37, D44).** D37 journals a cancelled turn as an interrupted assistant turn that ends
  with `turn_finished` (`interrupted: true`), so the page closes it instead of showing "…". D44
  joins a turn cut before any of its answer was heard to the next transcript within 5 s, so the
  model reads "El lunes, uno, de, dos de noviembre." as one answer (`test_ki07_…`).

## KI-08 · Wasted model rounds add latency

- **What happened.** `update_candidate` called two or three times in one turn with
  `unchanged` (seq 39, 47, 49, 60); `confirm_field` called in the same turn as the read-back
  (`same_turn`, 62). Each round costs 0.6–0.9 s; turns with them took 2.1–3.4 s to the first
  sentence.
- **Fix.** Prompt and next-step texts that end the round after a successful save; the runtime
  could stop the loop when a round only repeats an unchanged save.
- **Fixed (D44).** A call that changed nothing is `idle`. Once the question was said, an idle
  round ends the loop. A tool whose call changed nothing is not offered again that turn, so the
  next round has to speak. With a round modelled at 0.75 s, a save repeated twice goes from 4
  rounds and 3.0 s to the first sentence to 3 rounds and 2.3 s (`test_ki08_…`, two).

## KI-09 · A mention or a refusal of a language switches it; a frustrated request does not

- **Found by** the signals suite on synthetic turns (22 October 2026), not in a call.
- **What happens.** `explicit_controls` reads "Do I need to speak Spanish for this job?" and
  "No need to switch to Spanish, English is fine." in an English session as a request for
  Spanish, and "No hace falta que me hables en inglés, entiendo bien." as a request for
  English. "I already told you I don't speak Spanish! English please." matches both languages,
  so nothing switches. Over 122 cases × 2 the regex makes 6/190 false switches and misses
  12/38 requests, 10 of them indirect ("Sorry, my Spanish is not very good.").
- **Cause.** "speak Spanish" and "switch to Spanish" are request phrases with no request word
  around them; "no need" and "no hace falta que" are not negations in the pattern list; "don't
  speak Spanish" is read as a request for Spanish.
- **Fix proposed.** Decided by the Jev experiment: more anchored phrases and negations, or a
  classifier beside the turn (`evals/signals.py`).
- **Fixed (D52).** "speak"/"hablar" before a language count only after a request word ("can we",
  "rather", "puedes", "prefiero"), and a negation up to six words before a language request, in
  its clause, turns it down. The regex now makes no false switch on either signals set (0/95
  dev, 0/59 held-out, one repetition); the indirect requests it still misses (6/19, 9/18) are
  what the Jev analyzer is for (D52).


## KI-10 · No interview time is ever said: the model promises them and calls no tool

- **Found in** the hosted voice call of 22 October 2026, 13:01 UTC (session `e657bb5e…`,
  gpt-4.1, `ana_v19`, Langfuse traces).
- **What happens.** To "¿Te gustaría hacer una entrevista?" the candidate says "Sí."; Ana
  answers "Perfecto, te digo los huecos disponibles para entrevista." Then "Vale." gets "Aquí
  tienes las opciones de entrevista. ¿Con cuál te quedas?" and "No me has dado ninguna opción."
  gets "Ahora te los digo: aquí van los huecos…". Each turn has one model round and no tool
  call. The candidate ends up with a follow-up request instead of a booking.
- **Cause.** The times existed only behind `list_interview_slots`, which the model had to
  remember to call; the runtime's slot matcher works only once an offer exists.
- **Fixed (D56).** The confirmed brief puts the first three slots on offer, and the facts show
  them by number. The model says them without a tool. S28 replays the call with a model that
  never lists.

## KI-11 · An invented slot id makes the whole list be said again, up to four times

- **Found in** the hosted voice call of 22 October 2026, 11:30 UTC (session `14648365…`,
  gpt-4.1, `ana_v17`), and the candidate's own account: "me volvía en bucle a decirme los días
  hasta que en una me ha pillado".
- **What happens.**
  - "La última que me has dicho": the model calls
    `present_confirmation(slot_id="2026-10-24T17:00:00")` → refused "Offer fresh slots with
    list_interview_slots" → the runtime says the whole list again.
  - "El martes, de noviembre" is offered Tuesday 27 October.
  - "No, el martes veintisiete. A las diez" lists again (an invented id `slot-2026-10-27T10:30`)
    and then reads the slot back: two questions in one reply.
- **Cause.**
  - History holds only spoken text, so after the listing turn the model never sees an id.
  - The refusal told it to list again.
  - The runtime spoke every list.
  - The matcher threw the month away and searched only the offer.
- **Fixed (D56).**
  - Choice by number.
  - Refusals that name the options.
  - The list said by the model, not the runtime.
  - The month kept.
  - A day not on offer offered and its slot read back in the same turn.

  S29 replays it with a model that invents an id.

## KI-12 · Ana cuts the candidate off when they take a breath mid-sentence

- **Found in** the hosted voice call of 22 October 2026, 11:30 UTC (session `14648365…`, gpt-4.1,
  smart turn of D49), and the candidate's own account: "cuando hablaba, Ana me interrumpía".
- **What happens.** 12 of 32 turns were cancelled with `interrupted`. "Sí, soy español, pero lo
  que quiero saber es" ended a turn; the rest of the sentence cancelled it. Three of the cut
  parts were not joined, because the rest took longer than 5 s to finish, and the model saw
  them twice ("user: …mala reputación," then the whole sentence).
- **Cause.** A sentence that sounds finished ended after Pipecat's 0.2 s of VAD silence; any
  0.2 s of voice started a turn and cancelled the running one; the join window ran to the end
  of the continuation, not to its start; a joined fragment stayed in history.
- **Fixed (D57).** 0.5 s of silence after a finished-sounding sentence; turns start on words,
  two while Ana speaks; the window counts the pause; the fragment leaves the history. To be
  confirmed by voice on the hosted demo.

## KI-13 to KI-18 · The rest of the 22 October calls

Found in the hosted voice calls of 22 October 2026 (10:19 and 11:30 UTC, gpt-4.1, `ana_v17`),
read from the Langfuse traces and, for KI-18, the session's journal. Each is described with its
evidence, cause and fix under D58, one bullet per issue, in the order they landed. The
reproductions named in the table are the tests that went red first.

## KI-19 and KI-20 · Closing too soon (22 October, 14:23 and 14:33 UTC)

- **KI-19.** "Sí, no me lo expliques, he vivido por ahí, muchas gracias." after the booking
  matched the fixed farewell (D46) on "gracias": the session ended with no model round, Ana
  said goodbye and left, and "Ya está", "Pero no lo entiendo muy bien…" and "Cuelga" failed on
  the ended session. Fixed in D59: the farewell must be the whole utterance.
- **KI-20.** "No, muchas gracias. ¿Tienes alguna otra oferta?" with the brief confirmed: the
  model saved "no quiere entrevista", called `end_session`, and said goodbye; the question was
  never answered. Fixed in D59: `end_session` refuses while the message asks something.
