"""The voice session's surroundings: a fake runtime yielding scripted events, a recorder
standing in for TTS, and a session built with short timers."""

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator, Sequence
from datetime import UTC, datetime
from typing import Literal

from cafe_norte.conversation.contracts import (
    AssistantText,
    RuntimeEvent,
    TurnFinished,
    TurnInput,
    TurnStarted,
)
from cafe_norte.domain.contracts import SessionId, TurnId
from cafe_norte.errors import Language
from cafe_norte.observability.contracts import UsageRecord
from cafe_norte.voice.contracts import VoiceTexts
from cafe_norte.voice.session import VoiceSession
from tests.support.builders import SID

TEXTS: dict[Language, VoiceTexts] = {
    "es": VoiceTexts(
        opening="Hola, soy Ana.",
        filler="Un momento.",
        idle_prompt="¿Sigues ahí?",
        failure="Perdona, se me ha cortado. ¿Me lo repites?",
    ),
    "en": VoiceTexts(
        opening="Hi, I'm Ana.",
        filler="One moment.",
        idle_prompt="Still there?",
        failure="Sorry, I lost you there. Could you say that again?",
    ),
}


def say(text: str) -> AssistantText:
    return AssistantText(text=text, spoken_form=text)


def finished(turn: str = "t1") -> TurnFinished:
    return TurnFinished(turn_id=TurnId(turn), interrupted=False, usage=(), timings=())


class FakeRuntime:
    def __init__(
        self, scripts: list[list[RuntimeEvent]], *, slow: bool = False, language: Language = "es"
    ) -> None:
        self.scripts = scripts
        self.language = language
        self.turns: list[TurnInput] = []
        self.acks: list[tuple[TurnId, str, bool]] = []
        self.ended: list[str] = []
        self.said: list[str] = []
        self.asides: list[tuple[TurnId, str]] = []
        self.closed = 0
        self.slow = slow
        self.usage: list[UsageRecord] = []

    async def run_turn(self, turn: TurnInput) -> AsyncGenerator[RuntimeEvent, None]:
        self.turns.append(turn)
        events = self.scripts.pop(0)
        try:
            yield TurnStarted(turn_id=TurnId("t1"), language=self.language, text=turn.text)
            for event in events:
                if self.slow:
                    await asyncio.sleep(0.01)
                yield event
        finally:
            self.closed += 1

    async def delivered(self, turn_id: TurnId, *, text: str, complete: bool) -> None:
        self.acks.append((turn_id, text, complete))

    async def end(
        self, session_id: SessionId, reason: Literal["stop", "limit", "shutdown"]
    ) -> None:
        self.ended.append(reason)

    async def say(self, session_id: SessionId, text: str) -> AsyncIterator[RuntimeEvent]:
        """A journaled system turn: what the real runtime yields for a fixed sentence."""
        self.said.append(text)
        yield TurnStarted(turn_id=TurnId("sys"), language=self.language, text="")
        yield AssistantText(text=text, spoken_form=text)
        yield TurnFinished(turn_id=TurnId("sys"), interrupted=False, usage=(), timings=())

    async def aside(self, turn_id: TurnId, text: str) -> None:
        self.asides.append((turn_id, text))

    async def record_usage(self, session_id: SessionId, usage: Sequence[UsageRecord]) -> None:
        self.usage.extend(usage)


class Recorder:
    def __init__(self) -> None:
        self.spoken: list[str] = []
        self.status: list[str] = []

    async def speak(self, text: str) -> None:
        self.spoken.append(text)


def session(
    runtime: FakeRuntime, recorder: Recorder, language: Language = "es", **limits: float
) -> VoiceSession:
    return VoiceSession(
        runtime,
        SID,
        speak=recorder.speak,
        on_status=recorder.status.append,
        texts=TEXTS,
        language=language,
        clock=lambda: datetime(2026, 10, 20, tzinfo=UTC),
        idle_prompt_seconds=limits.get("prompt", 8.0),
    )
