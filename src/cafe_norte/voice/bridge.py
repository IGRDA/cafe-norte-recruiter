"""The three Pipecat ``FrameProcessor``s, which only map frames to ``VoiceSession`` methods, and
``UsageObserver``, which reads the providers' usage reports into the ``SpeechMeter``.

``SpeechTap`` sits before Pipecat's user aggregator, which consumes every transcript frame, so
it is the only place raw transcripts can be seen. ``InboundBridge`` sits after the aggregator
(which owns VAD, turn end, segment joining and interruptions) and before TTS: the aggregated
user message becomes one turn for the session, interruptions go to the session, raw transcripts
never reach TTS. ``PlaybackTap`` sits after the output transport, where ``TTSStoppedFrame``
arrives once the audio has actually played. Pipecat is imported here and in ``pipeline.py``
only."""

from typing import Protocol

from pipecat.frames.frames import (
    Frame,
    InterimTranscriptionFrame,
    InterruptionFrame,
    LLMContextFrame,
    MetricsFrame,
    TranscriptionFrame,
    TTSSpeakFrame,
    TTSStoppedFrame,
)
from pipecat.metrics.metrics import STTUsageMetricsData, TTSUsageMetricsData
from pipecat.observers.base_observer import BaseObserver, FramePushed
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from cafe_norte.voice.metering import SpeechMeter


class SessionPort(Protocol):
    async def transcript(self, text: str) -> None: ...
    async def interrupted(self) -> None: ...
    async def played_one(self) -> None: ...
    async def heard_speech(self) -> None: ...


class SpeechTap(FrameProcessor):
    """Any raw transcript, interim or final, is the candidate talking: not silence, even when
    VAD missed it. Every frame passes through untouched."""

    def __init__(self, session: SessionPort) -> None:
        super().__init__(name="speech-tap")
        self._session = session

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, InterimTranscriptionFrame | TranscriptionFrame):
            await self._session.heard_speech()
        await self.push_frame(frame, direction)


class InboundBridge(FrameProcessor):
    def __init__(self, session: SessionPort) -> None:
        super().__init__(name="runtime-bridge")
        self._session = session

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, InterimTranscriptionFrame | TranscriptionFrame):
            return  # raw words never reach TTS (the aggregator normally consumes them)
        if isinstance(frame, LLMContextFrame):
            text = _last_user_message(frame)
            frame.context.set_messages(
                []
            )  # the runtime keeps history; Pipecat's context stays empty
            if text:
                await self._session.transcript(text)
            return
        if isinstance(frame, InterruptionFrame):
            await self._session.interrupted()
        await self.push_frame(frame, direction)

    async def speak(self, text: str) -> None:
        await self.push_frame(TTSSpeakFrame(text=text))


class PlaybackTap(FrameProcessor):
    def __init__(self, session: SessionPort) -> None:
        super().__init__(name="playback-tap")
        self._session = session

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, TTSStoppedFrame):
            await self._session.played_one()
        await self.push_frame(frame, direction)


class UsageObserver(BaseObserver):
    """Deepgram reports the audio seconds it was sent and ElevenLabs the characters it was
    given, as ``MetricsFrame``s pushed on by every later processor; the first push is the
    provider's own report, so each is counted once wherever it travels (D44)."""

    def __init__(self, meter: SpeechMeter) -> None:
        super().__init__()
        self._meter = meter

    async def on_push_frame(self, data: FramePushed) -> None:
        if not (data.first_push and isinstance(data.frame, MetricsFrame)):
            return
        for item in data.frame.data:
            if isinstance(item, STTUsageMetricsData):
                self._meter.heard(item.value.audio_seconds)
            elif isinstance(item, TTSUsageMetricsData):
                self._meter.spoke(item.value)


def _last_user_message(frame: LLMContextFrame) -> str:
    for message in reversed(frame.context.get_messages()):
        if isinstance(message, dict) and message.get("role") == "user":
            content = message.get("content")
            return content.strip() if isinstance(content, str) else ""
    return ""
