# `voice`: Pipecat as the shell, not the brain

`Daily in → Deepgram → SpeechTap → user aggregator → InboundBridge → ElevenLabs → Daily out → PlaybackTap`.
Pipecat 1.13's `LLMUserAggregator` owns VAD, turn end, segment joining and interruptions and
emits the finished user message; everything voice *decides* lives in `VoiceSession`, plain
Python with no Pipecat import (D22).

| File | Contents |
| --- | --- |
| `contracts.py` | `Room`, `VoiceStatus`, `VoiceMode`, `VoiceTexts`, `VoiceTiming`, `room_expiry`, ports `RoomProvisioner`, `VoiceSessionController` |
| `delivery.py` | Pure ledger: sentences sent to TTS, sentences finished playing, `heard`, `readback_heard` |
| `metering.py` | Pure `SpeechMeter`: Deepgram's audio seconds, ElevenLabs' characters and each participant's minutes in the room, as measured, turned into `UsageRecord`s (D44) |
| `session.py` | `VoiceSession`: transcript → runtime turn, sentences → `speak` and the ledger, playback → `delivered(complete=True)`, interruption → cancel and `delivered(heard, complete=False)`, a turn cut before any of its answer was heard joined to the next transcript within 5 s (KI-07, D44), opening on join, filler while a tool runs long (journaled with `aside`), one silence prompt per candidate turn and the apology after a failed turn (both spoken through the runtime's journaled `say`), speech (an interruption or any raw transcript) restarts the silence clock, nothing system-said jumps the audio queue: every sentence goes through `_voice` into the ledger, and the apology, the silence prompt and the filler wait until what was sent has played (D40), `close` pauses the session once, a language change reported so STT follows; each in the language of the latest turn (D28, D35) |
| `bridge.py` | `SpeechTap` (before the aggregator, which consumes transcripts), `InboundBridge` (before TTS) and `PlaybackTap` (after the output transport): frames in, session methods out; `UsageObserver` reads the providers' usage reports into the meter, each counted on its first push only (D44) |
| `pipeline.py` | `user_side` (tap, aggregator, bridge: one assembly for the pipeline and its tests), `pipeline_params` (usage metrics on), the meter fed by the room's joins and leaves and recorded through `record_usage` once the pipeline has ended (D44), `PipecatVoiceController`: one pipeline task per session, join wait, stop, status, timing observations |
| `daily.py` | Private expiring rooms and two scoped tokens over Daily REST |
| `fake.py` | `FakeRooms`, `FakeVoiceController` for the API tests |

Required behaviours: barge-in stops queued speech and cancels generation; a committed booking
stays committed; an unplayed read-back is not "heard"; eight seconds in which the candidate heard nothing prompts once per candidate turn and never pauses a live call; a system sentence never plays ahead of or glued to audio still queued (D40); the session pauses when
the call ends (D35); everything Ana says is journaled. Timings are browser-observable
where possible and labelled as proxies otherwise.

Tests: `test_delivery.py` (pure, property-based), `test_voice_session.py` (fake runtime,
recorder, fast timers), `test_metering.py` (pure), `test_bridge.py` (Pipecat frames in memory; the transcript tap through
the real user aggregator via `user_side`), `test_daily.py` (scripted
transport), `test_api_voice.py` (fakes). The real providers are touched only by
`make voice-listen` and `make voice-smoke`, both manual.

Pipecat is an optional dependency (`uv sync --extra voice`); nothing outside this package
imports it, and `CAFE_NORTE_VOICE=off` leaves it unimported.
