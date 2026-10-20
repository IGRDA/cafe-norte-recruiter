"""The two Pipecat processors only map frames to ``VoiceSession`` methods."""

import pytest

pipecat = pytest.importorskip("pipecat")

from pipecat.frames.frames import (  # noqa: E402
    InterimTranscriptionFrame,
    InterruptionFrame,
    TranscriptionFrame,
    TTSSpeakFrame,
    TTSStoppedFrame,
)
from pipecat.tests.utils import run_test  # noqa: E402

from cafe_norte.voice.bridge import InboundBridge, PlaybackTap  # noqa: E402


class SessionSpy:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def transcript(self, text: str) -> None:
        self.calls.append(f"transcript:{text}")

    async def interrupted(self) -> None:
        self.calls.append("interrupted")

    async def played_one(self) -> None:
        self.calls.append("played_one")


async def test_inbound_passes_final_transcripts_to_the_session_and_drops_interims() -> None:
    spy = SessionSpy()
    bridge = InboundBridge(spy)
    frames = [
        InterimTranscriptionFrame(text="me lla", user_id="u", timestamp="0"),
        TranscriptionFrame(text="me llamo Lucía", user_id="u", timestamp="1"),
    ]
    await run_test(bridge, frames_to_send=frames, expected_down_frames=[])
    assert spy.calls == ["transcript:me llamo Lucía"]


async def test_inbound_relays_an_interruption_and_lets_it_through() -> None:
    """System frames skip the processor queue, which is why they are tested on their own."""
    spy = SessionSpy()
    bridge = InboundBridge(spy)
    await run_test(
        bridge, frames_to_send=[InterruptionFrame()], expected_down_frames=[InterruptionFrame]
    )
    assert spy.calls == ["interrupted"]


async def test_inbound_speak_pushes_a_tts_speak_frame() -> None:
    class Speaker(SessionSpy):
        bridge: InboundBridge

        async def transcript(self, text: str) -> None:
            await self.bridge.speak("Hola.")

    speaker = Speaker()
    bridge = InboundBridge(speaker)
    speaker.bridge = bridge
    down, _ = await run_test(
        bridge,
        frames_to_send=[TranscriptionFrame(text="hola", user_id="u", timestamp="1")],
        expected_down_frames=[TTSSpeakFrame],
    )
    assert any(isinstance(f, TTSSpeakFrame) and f.text == "Hola." for f in down)


async def test_the_playback_tap_counts_finished_sentences() -> None:
    spy = SessionSpy()
    tap = PlaybackTap(spy)
    await run_test(
        tap,
        frames_to_send=[TTSStoppedFrame(), TTSStoppedFrame()],
        expected_down_frames=[TTSStoppedFrame, TTSStoppedFrame],
    )
    assert spy.calls == ["played_one", "played_one"]
