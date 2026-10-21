"""Pipeline assembly for one session. Pipecat is imported here and in ``bridge.py`` only.

``Daily in → Deepgram → SpeechTap → user aggregator → InboundBridge → ElevenLabs → Daily out →
PlaybackTap``, watched by ``UsageObserver``: what the call used of each provider is measured and
recorded when the pipeline ends (D44).
Pipecat 1.13's ``LLMUserAggregator`` owns Silero VAD, the VAD start strategy (which interrupts
the bot), the speech-timeout stop strategy that waits for a transcript, and segment joining; it
emits the finished user message, which the bridge turns into one runtime turn. No smart-turn
model and no Pipecat LLM (D01, D22)."""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADAnalyzer
from pipecat.frames.frames import STTUpdateSettingsFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMUserAggregator,
    LLMUserAggregatorParams,
)
from pipecat.services.deepgram.stt import DeepgramSTTService, DeepgramSTTSettings
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService, ElevenLabsTTSSettings
from pipecat.transcriptions.language import Language as PipecatLanguage
from pipecat.transports.daily.transport import DailyParams, DailyTransport
from pipecat.turns.user_start.transcription_user_turn_start_strategy import (
    TranscriptionUserTurnStartStrategy,
)
from pipecat.turns.user_start.vad_user_turn_start_strategy import VADUserTurnStartStrategy
from pipecat.turns.user_stop.speech_timeout_user_turn_stop_strategy import (
    SpeechTimeoutUserTurnStopStrategy,
)
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.workers.runner import WorkerRunner

from cafe_norte.domain.contracts import SessionId
from cafe_norte.errors import Language, ServiceError
from cafe_norte.observability.contracts import StageTiming
from cafe_norte.voice.bridge import (
    InboundBridge,
    PlaybackTap,
    SessionPort,
    SpeechTap,
    UsageObserver,
)
from cafe_norte.voice.contracts import (
    STT_MODEL,
    TTS_MODEL,
    Room,
    VoiceStatus,
    VoiceTexts,
    VoiceTiming,
)
from cafe_norte.voice.metering import SpeechMeter
from cafe_norte.voice.session import VoiceRuntime, VoiceSession

log = logging.getLogger(__name__)

JOIN_TIMEOUT_SECONDS = 15.0
USER_SPEECH_TIMEOUT_SECONDS = 1.0  # a pause inside a sentence does not end the turn (D35)
STT_LANGUAGES: dict[Language, PipecatLanguage] = {
    "es": PipecatLanguage.ES,
    "en": PipecatLanguage.EN,
}


def stt_settings(language: Language) -> DeepgramSTTSettings:
    """Deepgram in the session's language: ``multi`` heard a Spanish "sí" as "C" (D35)."""
    return DeepgramSTTSettings(
        model=STT_MODEL, language=STT_LANGUAGES[language], interim_results=True
    )


def user_turn_strategies() -> UserTurnStrategies:
    """A turn starts on VAD or, when VAD misses a soft answer, on a transcript (Pipecat's own
    default pair); it ends after a full second of silence once the transcript is in."""
    return UserTurnStrategies(
        start=[
            VADUserTurnStartStrategy(enable_interruptions=True),
            TranscriptionUserTurnStartStrategy(),
        ],
        stop=[
            SpeechTimeoutUserTurnStopStrategy(
                user_speech_timeout=USER_SPEECH_TIMEOUT_SECONDS, wait_for_transcript=True
            )
        ],
    )


def pipeline_params() -> PipelineParams:
    """Usage metrics on: Deepgram's seconds and ElevenLabs' characters reach the meter only
    as usage reports (D44). Latency metrics stay off."""
    return PipelineParams(enable_metrics=False, enable_usage_metrics=True)


def user_side(
    session: SessionPort, vad: VADAnalyzer | None
) -> tuple[SpeechTap, LLMUserAggregator, InboundBridge]:
    """What sits between STT and TTS, in order: the speech tap, Pipecat's user aggregator and
    our bridge. One function, so the pipeline and the test that runs the real aggregator
    share it."""
    turns = LLMUserAggregator(
        LLMContext(),
        params=LLMUserAggregatorParams(
            vad_analyzer=vad, user_turn_strategies=user_turn_strategies()
        ),
    )
    return SpeechTap(session), turns, InboundBridge(session)


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
        live.task = asyncio.create_task(_run(live, lambda: self._report(session_id, live)))
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

    def _now(self) -> datetime:
        return self._clock() if self._clock is not None else datetime.now(UTC)

    async def _report(self, session_id: SessionId, live: "_Live") -> None:
        """What the call used, measured, once the pipeline has ended and the providers have
        flushed their last reports. A failure is logged: it never stops the call closing."""
        usage = live.meter.records(
            session_id, at=self._now(), stt_model=STT_MODEL, tts_model=TTS_MODEL
        )
        try:
            await self._runtime.record_usage(session_id, usage)
        except Exception:
            log.exception("speech usage not recorded session=%s", session_id)

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
        stt = DeepgramSTTService(api_key=self._deepgram_api_key, settings=stt_settings(language))
        tts = ElevenLabsTTSService(
            api_key=self._elevenlabs_api_key,
            settings=ElevenLabsTTSSettings(model=TTS_MODEL, voice=self._voice_id),
        )
        holder: dict[str, InboundBridge] = {}
        tasks: set[asyncio.Future[None]] = set()
        task_holder: dict[str, PipelineTask] = {}

        async def recognise_in(new: Language) -> None:
            """A language switch: Deepgram reconnects with the new language (Pipecat applies
            the settings delta and reconnects the stream)."""
            await task_holder["task"].queue_frame(
                STTUpdateSettingsFrame(delta=DeepgramSTTSettings(language=STT_LANGUAGES[new]))
            )

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
            on_language=lambda new: tasks.add(asyncio.ensure_future(recognise_in(new))),
        )
        user = user_side(session, SileroVADAnalyzer())
        holder["bridge"] = user[-1]
        pipeline = Pipeline(
            [
                transport.input(),
                stt,
                *user,
                tts,
                transport.output(),
                PlaybackTap(session),
            ]
        )
        meter = SpeechMeter()
        pipeline_task = PipelineTask(
            pipeline, params=pipeline_params(), observers=[UsageObserver(meter)]
        )
        task_holder["task"] = pipeline_task
        live = _Live(session=session, pipeline_task=pipeline_task, meter=meter)

        async def on_joined(_transport: object, _data: object) -> None:
            meter.entered("bot", self._now())
            live.joined.set()

        async def on_error(_transport: object, message: object) -> None:
            # A join failure is reported here; fail fast instead of waiting for the timeout.
            live.error = str(message)
            live.joined.set()

        async def on_first_participant_joined(_transport: object, _participant: object) -> None:
            meter.entered("candidate", self._now())
            await session.joined()

        async def on_participant_left(_transport: object, _p: object, _reason: object) -> None:
            meter.left("candidate", self._now())
            await pipeline_task.cancel()

        transport.add_event_handler("on_joined", on_joined)
        transport.add_event_handler("on_error", on_error)
        transport.add_event_handler("on_first_participant_joined", on_first_participant_joined)
        transport.add_event_handler("on_participant_left", on_participant_left)
        return live


async def _run(live: "_Live", report: Callable[[], Awaitable[None]]) -> None:
    """The pipeline until it ends for any reason; then what it used is recorded, the call is
    over and the session pauses (``VoiceSession.close`` is idempotent, so ``stop`` closing it
    first is fine)."""
    runner = WorkerRunner(handle_sigint=False)
    try:
        await runner.add_workers(live.pipeline_task)
        await runner.run()
    finally:
        await report()
        await live.session.close()


class _Live:
    def __init__(
        self, *, session: VoiceSession, pipeline_task: PipelineTask, meter: SpeechMeter
    ) -> None:
        self.session = session
        self.pipeline_task = pipeline_task
        self.meter = meter
        self.joined = asyncio.Event()
        self.error: str | None = None
        self.task: asyncio.Task[None] | None = None
