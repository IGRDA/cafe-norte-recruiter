"""The two Pipecat processors only map frames to ``VoiceSession`` methods."""

from typing import Any

import pytest

pipecat = pytest.importorskip("pipecat")

from pipecat.frames.frames import (  # noqa: E402
    InterimTranscriptionFrame,
    InterruptionFrame,
    LLMContextFrame,
    TranscriptionFrame,
    TTSSpeakFrame,
    TTSStoppedFrame,
)
from pipecat.processors.aggregators.llm_context import LLMContext  # noqa: E402
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

    async def heard_speech(self) -> None:
        self.calls.append("heard")


def user_turn(*messages: tuple[str, str]) -> LLMContextFrame:
    payload: list[Any] = [{"role": role, "content": content} for role, content in messages]
    return LLMContextFrame(LLMContext(messages=payload))


async def test_inbound_takes_the_aggregated_user_message_as_the_turn() -> None:
    """Pipecat's user aggregator owns VAD, turn end and segment joining; it emits the context
    with the finished user message. Raw transcripts, interim or final, never reach TTS."""
    spy = SessionSpy()
    bridge = InboundBridge(spy)
    frames = [
        InterimTranscriptionFrame(text="me lla", user_id="u", timestamp="0"),
        TranscriptionFrame(text="me llamo Lucía Marín", user_id="u", timestamp="1"),
        user_turn(("user", "me llamo Lucía Marín")),
        user_turn(("user", "me llamo Lucía Marín"), ("user", "sí me interesa")),
        user_turn(("assistant", "¿Y tu nombre?")),  # no user message: not a turn
    ]
    await run_test(bridge, frames_to_send=frames, expected_down_frames=[])
    assert [c for c in spy.calls if c != "heard"] == [
        "transcript:me llamo Lucía Marín",
        "transcript:sí me interesa",
    ]


async def test_any_raw_transcript_tells_the_session_speech_was_heard() -> None:
    spy = SessionSpy()
    frames = [
        InterimTranscriptionFrame(text="s", user_id="u", timestamp="0"),
        TranscriptionFrame(text="sí", user_id="u", timestamp="1"),
    ]
    await run_test(InboundBridge(spy), frames_to_send=frames, expected_down_frames=[])
    assert spy.calls == ["heard", "heard"]


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
        frames_to_send=[user_turn(("user", "hola"))],
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
