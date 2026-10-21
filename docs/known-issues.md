# Known issues

Problems seen in real calls that are documented, reproduced where possible, and left for a
later stage. Each entry says what happened, the evidence, the cause, how to reproduce it and
the fix proposed. A reproduction in `tests/test_known_issues.py` is a strict `xfail`: it fails
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
| KI-01 | "Está todo bien" is not taken as a yes | High | `test_ki01_…` | runtime yes/no |
| KI-02 | A yes to the summary on screen is lost when its audio was cut; the summary loops | High | `test_ki02_…` | read-back design |
| KI-03 | "¿Sigues ahí?" while the candidate is speaking | High | `test_ki03_…` | voice session |
| KI-04 | "¿Sigues ahí?" twice after a failed turn | Medium | `test_ki04_…` | voice session |
| KI-05 | System sentences are said ahead of the audio still playing | Medium | `test_ki05_…` | voice session |
| KI-06 | Choosing an interview slot loops and never books | High | manual (below) | booking, observability |
| KI-07 | A hesitation splits the answer and the first part is lost silently | Medium | manual (below) | runtime robustness |
| KI-08 | Wasted model rounds add latency | Low | journal | runtime, prompt |

## KI-01 · "Está todo bien" is not taken as a yes

- **What happened.** "Sí, está todo bien." (seq 87), "Está todo bien." (116) and "Está todo bien.
  Todo correcto." (131) were left to the model, which did not call `confirm_brief`.
- **Cause.** `signals.answer_to_readback` matches whole phrases; "está todo bien" has "todo"
  between "está" and "bien", so no listed phrase covers it and the leftover word makes it "not
  plain".
- **Fix.** Add "está todo bien", "todo bien", "está bien todo", "todo está bien" (and the
  English "all good", "that's all right") to the affirmations; consider word-set matching for
  the "todo / bien / correcto" family.

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

## KI-04 · "¿Sigues ahí?" twice after a failed turn

- **What happened.** The apology at 16:09:04, "¿Sigues ahí?" at 16:09:12 and again at 16:09:28.
- **Cause.** The failure path starts the silence clock at once; when the failed turn's queued
  sentences finish playing, `played_one` acknowledges the turn and starts the clock again.
- **Reproduce.** `test_ki04_…`.
- **Fix.** One clock per listening period: the failure path acknowledges the turn first, or
  `_maybe_acknowledge` does not re-arm a clock that is already running.

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

## KI-07 · A hesitation splits the answer and the first part is lost silently

- **What happened.** "El lunes," (seq 53) and "uno, de, dos de noviembre." (54) became two
  turns 4 s apart; the first was cancelled by the second without a `turn_finished` or
  `turn_failed`, and the page showed "…" for it.
- **Cause.** A pause longer than the 1.0 s speech timeout ends the turn; a new turn interrupts
  the running one; cancellation is not journaled (runtime robustness item).
- **Fix.** Journal the cancelled turn as interrupted (runtime robustness stream); consider a
  longer timeout after a question that expects a date or a number, or Pipecat's smart-turn.

## KI-08 · Wasted model rounds add latency

- **What happened.** `update_candidate` called two or three times in one turn with
  `unchanged` (seq 39, 47, 49, 60); `confirm_field` called in the same turn as the read-back
  (`same_turn`, 62). Each round costs 0.6–0.9 s; turns with them took 2.1–3.4 s to the first
  sentence.
- **Fix.** Prompt and next-step texts that end the round after a successful save; the runtime
  could stop the loop when a round only repeats an unchanged save.
