"""Pipeline assembly for one session. Pipecat is imported here and in ``bridge.py`` only.

``Daily in → Deepgram → user aggregator → InboundBridge → ElevenLabs → Daily out → PlaybackTap``.
Pipecat 1.13's ``LLMUserAggregator`` owns Silero VAD, the VAD start strategy (which interrupts
the bot), the speech-timeout stop strategy that waits for a transcript, and segment joining; it
emits the finished user message, which the bridge turns into one runtime turn. No smart-turn
model and no Pipecat LLM (D01, D22)."""

import asyncio
from collections.abc import Callable, Mapping
from datetime import datetime

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMUserAggregator,
    LLMUserAggregatorParams,
)
from pipecat.services.deepgram.stt import DeepgramSTTService, DeepgramSTTSettings
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService, ElevenLabsTTSSettings
from pipecat.transports.daily.transport import DailyParams, DailyTransport
from pipecat.turns.user_start.vad_user_turn_start_strategy import VADUserTurnStartStrategy
from pipecat.turns.user_stop.speech_timeout_user_turn_stop_strategy import (
    SpeechTimeoutUserTurnStopStrategy,
)
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.workers.runner import WorkerRunner

from cafe_norte.domain.contracts import SessionId
from cafe_norte.errors import Language, ServiceError
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
        texts: Mapping[Language, VoiceTexts],
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

    async def start(self, session_id: SessionId, room: Room, language: Language) -> None:
        """Returns once the bot has joined; a failure leaves no task, room slot or session."""
        live = self.build(session_id, room, language)
        self._sessions[session_id] = live
        live.task = asyncio.create_task(_run(live))
        live.task.add_done_callback(lambda _t: self._forget(session_id, live))
        try:
            await asyncio.wait_for(live.joined.wait(), JOIN_TIMEOUT_SECONDS)
        except TimeoutError as error:
            await self.stop(session_id, reason="join_timeout")
            raise ServiceError(
                "the bot did not join the room", code="provider_unavailable"
            ) from error
        failed = live.task.done() and live.task.exception() is not None
        if live.error is not None or failed:
            detail = live.error or "voice pipeline failed to start"
            await self.stop(session_id, reason="start_failed")
            raise ServiceError(f"daily: {detail}", code="provider_unavailable")

    async def stop(self, session_id: SessionId, *, reason: str) -> None:
        live = self._sessions.pop(session_id, None)
        if live is None:
            return
        await live.session.close()
        await live.pipeline_task.cancel()
        if live.task is not None:
            await asyncio.gather(live.task, return_exceptions=True)

    async def wait(self, session_id: SessionId) -> None:
        live = self._sessions.get(session_id)
        if live is not None and live.task is not None:
            await asyncio.gather(live.task, return_exceptions=True)

    def _forget(self, session_id: SessionId, live: "_Live") -> None:
        """The pipeline ended for any reason: the session is no longer running here."""
        if self._sessions.get(session_id) is live:
            self._sessions.pop(session_id, None)

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

    def build(self, session_id: SessionId, room: Room, language: Language) -> "_Live":
        transport = DailyTransport(
            room.room_url,
            room.bot_token,
            "Ana",
            DailyParams(audio_in_enabled=True, audio_out_enabled=True, video_out_enabled=False),
        )
        stt = DeepgramSTTService(
            api_key=self._deepgram_api_key,
            settings=DeepgramSTTSettings(model="nova-3", language="multi", interim_results=True),
        )
        tts = ElevenLabsTTSService(
            api_key=self._elevenlabs_api_key,
            settings=ElevenLabsTTSSettings(model="eleven_flash_v2_5", voice=self._voice_id),
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
            language=language,
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
        live = _Live(session=session, pipeline_task=pipeline_task)

        async def on_joined(_transport: object, _data: object) -> None:
            live.joined.set()

        async def on_error(_transport: object, message: object) -> None:
            # A join failure is reported here; fail fast instead of waiting for the timeout.
            live.error = str(message)
            live.joined.set()

        async def on_first_participant_joined(_transport: object, _participant: object) -> None:
            await session.joined()

        async def on_participant_left(_transport: object, _p: object, _reason: object) -> None:
            await pipeline_task.cancel()

        transport.add_event_handler("on_joined", on_joined)
        transport.add_event_handler("on_error", on_error)
        transport.add_event_handler("on_first_participant_joined", on_first_participant_joined)
        transport.add_event_handler("on_participant_left", on_participant_left)
        return live


async def _run(live: "_Live") -> None:
    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(live.pipeline_task)
    await runner.run()


class _Live:
    def __init__(self, *, session: VoiceSession, pipeline_task: PipelineTask) -> None:
        self.session = session
        self.pipeline_task = pipeline_task
        self.joined = asyncio.Event()
        self.error: str | None = None
        self.task: asyncio.Task[None] | None = None
