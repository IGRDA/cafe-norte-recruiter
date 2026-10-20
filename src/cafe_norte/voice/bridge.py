"""The two Pipecat ``FrameProcessor``s. They only map frames to ``VoiceSession`` methods.

``InboundBridge`` sits between STT and TTS: final transcripts and interruptions go to the
session, interim transcripts are dropped, everything else passes. ``PlaybackTap`` sits after
the output transport, where ``TTSStoppedFrame`` arrives once the audio has actually played.
Pipecat is imported here and in ``pipeline.py`` only."""

from typing import Protocol

from pipecat.frames.frames import (
    Frame,
    InterimTranscriptionFrame,
    InterruptionFrame,
    TranscriptionFrame,
    TTSSpeakFrame,
    TTSStoppedFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


class SessionPort(Protocol):
    async def transcript(self, text: str) -> None: ...
    async def interrupted(self) -> None: ...
    async def played_one(self) -> None: ...


class InboundBridge(FrameProcessor):
    def __init__(self, session: SessionPort) -> None:
        super().__init__(name="runtime-bridge")
        self._session = session

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, InterimTranscriptionFrame):
            return  # provisional text is never evidence
        if isinstance(frame, TranscriptionFrame):
            await self._session.transcript(frame.text)
            return  # never let the candidate's words reach TTS
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
