# `voice`: Pipecat as the shell, not the brain

The pipeline is `Daily in → VAD + turn detection → Deepgram → RuntimeBridge → ElevenLabs → Daily out`.
`RuntimeBridge` is the only Pipecat-aware class that touches conversation logic: it turns a
finalized transcription frame into a `TurnInput`, iterates `ConversationRuntime.run_turn`, emits
each `AssistantText.spoken_form` as a text frame, and on an interruption frame closes the
generator and reports what was delivered.

| File | Contents |
| --- | --- |
| `contracts.py` | `Room`, `VoiceStatus`, `VoiceTiming`, ports `RoomProvisioner`, `VoiceSessionController` |
| `bridge.py` | `RuntimeBridge` (Pipecat `FrameProcessor`) |
| `pipeline.py` | Builds the pipeline for one session with pinned VAD/turn-detection settings |
| `daily.py` | Private rooms, short-lived tokens, expiry and ejection |
| `fake.py` | Fakes for rooms and controller so the API is testable without Pipecat |

Required behaviours: barge-in stops queued speech and cancels generation; a committed booking
stays committed; an unplayed read-back is not "heard"; eight seconds of silence prompts once,
twelve more pauses the session and releases voice resources. Timings are browser-observable
where possible and labelled as proxies otherwise.

Pipecat is an optional dependency (`uv sync --extra voice`); nothing outside this package
imports it, and `CAFE_NORTE_VOICE=off` leaves it unimported.
