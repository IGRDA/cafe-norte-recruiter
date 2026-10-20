"""Pipeline assembly for one session. Pipecat is imported here and in ``bridge.py`` only.

``Daily in → Deepgram → user aggregator → InboundBridge → ElevenLabs → Daily out → PlaybackTap``.
Pipecat 1.13's ``LLMUserAggregator`` owns Silero VAD, the VAD start strategy (which interrupts
the bot), the speech-timeout stop strategy that waits for a transcript, and segment joining; it
emits the finished user message, which the bridge turns into one runtime turn. No smart-turn
model and no Pipecat LLM (D01, D22)."""

import asyncio
from collections.abc import Callable
from datetime import datetime

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMUserAggregator,
    LLMUserAggregatorParams,
)
from pipecat.services.deepgram.stt import DeepgramSTTService, LiveOptions
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.transports.daily.transport import DailyParams, DailyTransport
from pipecat.turns.user_start.vad_user_turn_start_strategy import VADUserTurnStartStrategy
from pipecat.turns.user_stop.speech_timeout_user_turn_stop_strategy import (
    SpeechTimeoutUserTurnStopStrategy,
)
from pipecat.turns.user_turn_strategies import UserTurnStrategies

from cafe_norte.domain.contracts import SessionId
from cafe_norte.errors import ServiceError
from cafe_norte.observability.contracts import StageTiming
from cafe_norte.voice.bridge import InboundBridge, PlaybackTap
from cafe_norte.voice.contracts import Room, VoiceStatus, VoiceTexts, VoiceTiming
from cafe_norte.voice.session import VoiceRuntime, VoiceSession

JOIN_TIMEOUT_SECONDS = 15.0
USER_SPEECH_TIMEOUT_SECONDS = 0.6  # Pipecat's default pause before a turn is considered over


class PipecatVoiceController:
    """Implements ``VoiceSessionController``: one Pipecat task per session inside this
    container. Provider connections are per call; nothing is warmed; ``stop`` or SIGTERM
    releases everything."""

    def __init__(
        self,
        runtime: VoiceRuntime,
        *,
        deepgram_api_key: str,
        elevenlabs_api_key: str,
        voice_id: str,
        texts: VoiceTexts,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._runtime = runtime
        self._deepgram_api_key = deepgram_api_key
        self._elevenlabs_api_key = elevenlabs_api_key
        self._voice_id = voice_id
        self._texts = texts
        self._clock = clock
        self._sessions: dict[SessionId, _Live] = {}
        self._observed: dict[SessionId, list[VoiceTiming]] = {}

    async def start(self, session_id: SessionId, room: Room) -> None:
        """Returns once the bot has joined; a failure leaves no task behind."""
        live = self.build(session_id, room)
        self._sessions[session_id] = live
        live.task = asyncio.create_task(live.runner.run(live.pipeline_task))
        try:
            await asyncio.wait_for(live.joined.wait(), JOIN_TIMEOUT_SECONDS)
        except TimeoutError as error:
            await self.stop(session_id, reason="join_timeout")
            raise ServiceError(
                "the bot did not join the room", code="provider_unavailable"
            ) from error
        if live.task.done() and live.task.exception() is not None:
            self._sessions.pop(session_id, None)
            raise ServiceError("voice pipeline failed to start", code="provider_unavailable")

    async def stop(self, session_id: SessionId, *, reason: str) -> None:
        live = self._sessions.pop(session_id, None)
        if live is None:
            return
        await live.session.close()
        await live.pipeline_task.cancel()
        if live.task is not None:
            await asyncio.gather(live.task, return_exceptions=True)

    def status(self, session_id: SessionId) -> VoiceStatus | None:
        live = self._sessions.get(session_id)
        return live.session.status if live is not None else None

    def observe(self, timing: VoiceTiming) -> None:
        self._observed.setdefault(timing.session_id, []).append(timing)

    def timings(self, session_id: SessionId) -> tuple[StageTiming, ...]:
        return ()  # paired from the observations at the measurement stage

    def observations(self, session_id: SessionId) -> tuple[VoiceTiming, ...]:
        return tuple(self._observed.get(session_id, ()))

    # ---- assembly --------------------------------------------------------------------------------

    def build(self, session_id: SessionId, room: Room) -> "_Live":
        transport = DailyTransport(
            room.room_url,
            room.bot_token,
            "Ana",
            DailyParams(audio_in_enabled=True, audio_out_enabled=True, video_out_enabled=False),
        )
        stt = DeepgramSTTService(
            api_key=self._deepgram_api_key,
            live_options=LiveOptions(model="nova-3", language="es", interim_results=True),
        )
        tts = ElevenLabsTTSService(
            api_key=self._elevenlabs_api_key, voice_id=self._voice_id, model="eleven_flash_v2_5"
        )
        turns = LLMUserAggregator(
            LLMContext(),
            params=LLMUserAggregatorParams(
                vad_analyzer=SileroVADAnalyzer(),
                user_turn_strategies=UserTurnStrategies(
                    start=[VADUserTurnStartStrategy(enable_interruptions=True)],
                    stop=[
                        SpeechTimeoutUserTurnStopStrategy(
                            user_speech_timeout=USER_SPEECH_TIMEOUT_SECONDS,
                            wait_for_transcript=True,
                        )
                    ],
                ),
            ),
        )
        holder: dict[str, InboundBridge] = {}

        async def speak(text: str) -> None:
            await holder["bridge"].speak(text)

        session = VoiceSession(
            self._runtime,
            session_id,
            speak=speak,
            on_status=lambda _status: None,
            texts=self._texts,
            clock=self._clock,
        )
        bridge = InboundBridge(session)
        holder["bridge"] = bridge
        pipeline = Pipeline(
            [
                transport.input(),
                stt,
                turns,
                bridge,
                tts,
                transport.output(),
                PlaybackTap(session),
            ]
        )
        pipeline_task = PipelineTask(pipeline, params=PipelineParams(enable_metrics=False))
        joined = asyncio.Event()

        async def on_joined(_transport: object, _data: object) -> None:
            joined.set()

        async def on_first_participant_joined(_transport: object, _participant: object) -> None:
            await session.joined()

        async def on_participant_left(_transport: object, _p: object, _reason: object) -> None:
            await pipeline_task.cancel()

        transport.add_event_handler("on_joined", on_joined)
        transport.add_event_handler("on_first_participant_joined", on_first_participant_joined)
        transport.add_event_handler("on_participant_left", on_participant_left)

        return _Live(
            session=session,
            pipeline_task=pipeline_task,
            runner=PipelineRunner(handle_sigint=False),
            joined=joined,
        )


class _Live:
    def __init__(
        self,
        *,
        session: VoiceSession,
        pipeline_task: PipelineTask,
        runner: PipelineRunner,
        joined: asyncio.Event,
    ) -> None:
        self.session = session
        self.pipeline_task = pipeline_task
        self.runner = runner
        self.joined = joined
        self.task: asyncio.Task[None] | None = None
