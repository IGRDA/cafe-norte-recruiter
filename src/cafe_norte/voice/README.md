# `voice`: Pipecat as the shell, not the brain

`Daily in → Deepgram → user aggregator → InboundBridge → ElevenLabs → Daily out → PlaybackTap`.
Pipecat 1.13's `LLMUserAggregator` owns VAD, turn end, segment joining and interruptions and
emits the finished user message; everything voice *decides* lives in `VoiceSession`, plain
Python with no Pipecat import (D22).

| File | Contents |
| --- | --- |
| `contracts.py` | `Room`, `VoiceStatus`, `VoiceMode`, `VoiceTexts`, `VoiceTiming`, `room_expiry`, ports `RoomProvisioner`, `VoiceSessionController` |
| `delivery.py` | Pure ledger: sentences sent to TTS, sentences finished playing, `heard`, `readback_heard` |
| `session.py` | `VoiceSession`: transcript → runtime turn, sentences → `speak` and the ledger, playback → `delivered(complete=True)`, interruption → cancel and `delivered(heard, complete=False)`, opening on join, filler while a tool runs long (journaled with `aside`), one silence prompt and the apology after a failed turn (both spoken through the runtime's journaled `say`), any raw transcript resets the silence clock, `close` pauses the session once, a language change reported so STT follows; each in the language of the latest turn (D28, D35) |
| `bridge.py` | `InboundBridge` (before TTS) and `PlaybackTap` (after the output transport): frames in, session methods out |
| `pipeline.py` | `PipecatVoiceController`: one pipeline task per session, join wait, stop, status, timing observations |
| `daily.py` | Private expiring rooms and two scoped tokens over Daily REST |
| `fake.py` | `FakeRooms`, `FakeVoiceController` for the API tests |

Required behaviours: barge-in stops queued speech and cancels generation; a committed booking
stays committed; an unplayed read-back is not "heard"; eight seconds of silence prompts once and never pauses a live call; the session pauses when
the call ends (D35); everything Ana says is journaled. Timings are browser-observable
where possible and labelled as proxies otherwise.

Tests: `test_delivery.py` (pure, property-based), `test_voice_session.py` (fake runtime,
recorder, fast timers), `test_bridge.py` (Pipecat frames in memory), `test_daily.py` (scripted
transport), `test_api_voice.py` (fakes). The real providers are touched only by
`make voice-listen` and `make voice-smoke`, both manual.

Pipecat is an optional dependency (`uv sync --extra voice`); nothing outside this package
imports it, and `CAFE_NORTE_VOICE=off` leaves it unimported.
