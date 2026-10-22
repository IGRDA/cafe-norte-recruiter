"""Pipeline assembly for one session. Pipecat is imported here and in ``bridge.py`` only.

``Daily in → Deepgram → SpeechTap → user aggregator → InboundBridge → ElevenLabs → Daily out →
PlaybackTap``, watched by ``UsageObserver``: what the call used of each provider is measured and
recorded when the pipeline ends.
Pipecat 1.13's ``LLMUserAggregator`` owns Silero VAD, the VAD start strategy (which interrupts
the bot), the speech-timeout stop strategy that waits for a transcript, and segment joining; it
emits the finished user message, which the bridge turns into one runtime turn. No smart-turn
model and no Pipecat LLM."""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime

import aiohttp
from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADAnalyzer, VADParams
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMUserAggregator,
    LLMUserAggregatorParams,
)
from pipecat.services.deepgram.stt import DeepgramSTTService, DeepgramSTTSettings
from pipecat.services.elevenlabs.tts import ElevenLabsHttpTTSSettings
from pipecat.transports.daily.transport import DailyParams, DailyTransport
from pipecat.turns.user_start.min_words_user_turn_start_strategy import (
    MinWordsUserTurnStartStrategy,
)
from pipecat.turns.user_stop.turn_analyzer_user_turn_stop_strategy import (
    TurnAnalyzerUserTurnStopStrategy,
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
from cafe_norte.voice.tts import PrefetchingElevenLabsHttpTTSService

log = logging.getLogger(__name__)

JOIN_TIMEOUT_SECONDS = 15.0
# After the bot joins, the page joins at once; a candidate still missing after this never
# connected (a closed tab, a blocked page). Ending the call frees its voice place instead of
# holding it until Pipecat's five-minute idle timeout.
CANDIDATE_JOIN_SECONDS = 30.0
# A turn that sounds unfinished waits this long for more words (smart turn); one that
# sounds finished ends after FINISHED_TURN_SILENCE_SECONDS, up from Pipecat's 0.2 s, which cut
# a candidate taking a breath mid-sentence. While Ana speaks, BARGE_IN_WORDS words cut her.
UNFINISHED_TURN_SILENCE_SECONDS = 2.0
FINISHED_TURN_SILENCE_SECONDS = 0.5
BARGE_IN_WORDS = 2
# Recognition is multilingual regardless of the reply language; changing the reply
# language must not prevent recognition of the candidate's next utterance.
STT_LANGUAGE = "multi"


def stt_settings() -> DeepgramSTTSettings:
    """Deepgram nova-3 in ``multi``: Spanish and English (and fr, de, pt, it) in one call."""
    return DeepgramSTTSettings(model=STT_MODEL, language=STT_LANGUAGE, interim_results=True)


def tts_settings(voice_id: str) -> ElevenLabsHttpTTSSettings:
    """v4 Turbo over HTTP, one request per sentence. Chosen by listening: the same
    intonation across sentences and messages, loosened so it does not sound read. v4 ignores
    ``speed``, so none is set."""
    return ElevenLabsHttpTTSSettings(
        model=TTS_MODEL, voice=voice_id, stability=0.4, similarity_boost=0.8, style=0.2
    )


def vad_params() -> VADParams:
    """Silero's defaults but the silence that ends speech: what the smart-turn model then judges
    as finished or not."""
    return VADParams(stop_secs=FINISHED_TURN_SILENCE_SECONDS)


def user_turn_strategies() -> UserTurnStrategies:
    """A turn starts on words, so a soft "sí" VAD misses still counts and a cough or an
    "mhm" over Ana does not cut her: while she speaks it takes ``BARGE_IN_WORDS`` words.
    It ends when the bundled smart-turn model hears a finished sentence and the final
    transcript is in, or after ``UNFINISHED_TURN_SILENCE_SECONDS`` of silence. One
    analyzer per call: it keeps the call's audio."""
    return UserTurnStrategies(
        start=[MinWordsUserTurnStartStrategy(min_words=BARGE_IN_WORDS, enable_interruptions=True)],
        stop=[
            TurnAnalyzerUserTurnStopStrategy(
                turn_analyzer=LocalSmartTurnAnalyzerV3(
                    params=SmartTurnParams(stop_secs=UNFINISHED_TURN_SILENCE_SECONDS)
                ),
                wait_for_transcript=True,
            )
        ],
    )


def pipeline_params() -> PipelineParams:
    """Usage metrics on: Deepgram's seconds and ElevenLabs' characters reach the meter only
    as usage reports. Latency metrics stay off."""
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


async def end_unless_joined(
    joined: asyncio.Event,
    end: Callable[[], Awaitable[None]],
    *,
    seconds: float,
    sleep: Callable[[float], Awaitable[None]],
) -> bool:
    """Wait ``seconds`` for the candidate; if they have not joined, ``end`` the call. True when
    it ended it."""
    arrived = asyncio.ensure_future(joined.wait())
    deadline = asyncio.ensure_future(sleep(seconds))
    try:
        await asyncio.wait({arrived, deadline}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        arrived.cancel()
        deadline.cancel()
    if joined.is_set():
        return False
    await end()
    return True


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
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._runtime = runtime
        self._sleep = sleep
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
        live.watch = asyncio.create_task(
            end_unless_joined(
                live.candidate_joined,
                lambda: self._nobody_came(session_id, live),
                seconds=CANDIDATE_JOIN_SECONDS,
                sleep=self._sleep,
            )
        )

    async def _nobody_came(self, session_id: SessionId, live: "_Live") -> None:
        log.info(
            "voice: no candidate joined within %.0f s session=%s",
            CANDIDATE_JOIN_SECONDS,
            session_id,
        )
        await live.pipeline_task.cancel()

    async def stop(self, session_id: SessionId, *, reason: str) -> None:
        live = self._sessions.pop(session_id, None)
        if live is None:
            return
        if live.watch is not None:
            live.watch.cancel()
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
        if live.watch is not None:
            live.watch.cancel()
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
        stt = DeepgramSTTService(api_key=self._deepgram_api_key, settings=stt_settings())
        http = aiohttp.ClientSession()  # one per call, so sentences reuse its connection
        tts = PrefetchingElevenLabsHttpTTSService(
            api_key=self._elevenlabs_api_key,
            aiohttp_session=http,
            settings=tts_settings(self._voice_id),
        )
        holder: dict[str, InboundBridge] = {}
        task_holder: dict[str, PipelineTask] = {}

        async def speak(text: str) -> None:
            await holder["bridge"].speak(text)

        async def hang_up() -> None:
            """Graceful: what is in flight drains before Ana leaves the room."""
            await task_holder["task"].end(reason="goodbye")

        session = VoiceSession(
            self._runtime,
            session_id,
            speak=speak,
            on_status=lambda _status: None,
            texts=self._texts,
            language=language,
            clock=self._clock,
            on_hang_up=hang_up,
        )
        user = user_side(session, SileroVADAnalyzer(params=vad_params()))
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
        live = _Live(session=session, pipeline_task=pipeline_task, meter=meter, http=http)

        async def on_joined(_transport: object, _data: object) -> None:
            meter.entered("bot", self._now())
            live.joined.set()

        async def on_error(_transport: object, message: object) -> None:
            # A join failure is reported here; fail fast instead of waiting for the timeout.
            live.error = str(message)
            live.joined.set()

        async def on_first_participant_joined(_transport: object, _participant: object) -> None:
            live.candidate_joined.set()
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
        await live.http.close()


class _Live:
    def __init__(
        self,
        *,
        session: VoiceSession,
        pipeline_task: PipelineTask,
        meter: SpeechMeter,
        http: aiohttp.ClientSession,
    ) -> None:
        self.session = session
        self.pipeline_task = pipeline_task
        self.meter = meter
        self.http = http
        self.joined = asyncio.Event()
        self.candidate_joined = asyncio.Event()
        self.error: str | None = None
        self.task: asyncio.Task[None] | None = None
        self.watch: asyncio.Task[bool] | None = None  # ends the call if nobody joins
