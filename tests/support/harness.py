"""The runtime harness: the real runtime, handlers and memory store behind a scripted model."""

import asyncio
import json
from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence
from datetime import datetime
from typing import Any

from cafe_norte.conversation.contracts import RuntimeEvent, SignalAnalyzer, ToolStarted, TurnInput
from cafe_norte.conversation.runtime import Limits
from cafe_norte.conversation.signals import DecisionSignalAnalyzer
from cafe_norte.domain.contracts import InputId, SessionId, SlotId
from cafe_norte.errors import Language
from cafe_norte.model.contracts import (
    ChoiceAnswer,
    Decision,
    ModelEvent,
    ModelFinished,
    ModelMessage,
    ModelText,
    ToolCall,
)
from cafe_norte.model.fake import FakeDecisionModel, FakeModel
from cafe_norte.observability.contracts import UsageRecord
from cafe_norte.observability.fakes import RecordingTelemetry
from cafe_norte.persistence.contracts import EventRecord
from cafe_norte.persistence.memory import MemoryStore
from cafe_norte.persistence.seed import seed_calendar
from tests.support.app import build_runtime
from tests.support.builders import CONFIGS, NOW, SESSION, STAMP, full_record, session_state

STOP = ModelFinished(reason="stop")
WANTS_TOOLS = ModelFinished(reason="tool_calls")

FAST_DEADLINE = Limits(llm_first_output_seconds=0.05)

TUE_17 = SlotId("chamberi_barista_v1-2026-10-20-1700")
WED_1030 = SlotId("chamberi_barista_v1-2026-10-21-1030")
FRI_1030 = SlotId("chamberi_barista_v1-2026-10-23-1030")
FRI_17 = SlotId("chamberi_barista_v1-2026-10-23-1700")


def says(*parts: str) -> list[ModelEvent]:
    """One model call that streams ``parts`` and stops."""
    return [*(ModelText(text=p) for p in parts), STOP]


def name_call(call_id: str = "c1", name: str = "Lucía") -> ToolCall:
    return ToolCall(
        call_id=call_id,
        name="update_candidate",
        arguments_json=json.dumps({"patch": {"name": name}, "evidence_text": f"Soy {name}"}),
    )


DATE_CALL = ToolCall(
    call_id="d1",
    name="update_candidate",
    arguments_json=json.dumps(
        {"patch": {"earliest_start_date": "2026-11-02"}, "evidence_text": "El 2 de noviembre"}
    ),
)


def present_brief(call_id: str = "p1") -> ToolCall:
    return ToolCall(
        call_id=call_id, name="present_confirmation", arguments_json='{"target": "brief"}'
    )


def offer_call(date_preference: str | None = None) -> ToolCall:
    payload = {"evidence_text": "Sí, quiero entrevista."}
    if date_preference is not None:
        payload["date_preference"] = date_preference
    return ToolCall(call_id="o1", name="list_interview_slots", arguments_json=json.dumps(payload))


def turn(text: str, input_id: str = "in-1") -> TurnInput:
    return TurnInput(
        session_id=SESSION,
        input_id=InputId(input_id),
        text=text,
        channel="text",
        received_at=NOW,
    )


class SlowFirst(FakeModel):
    """The first ``slow_calls`` model calls never say anything, as a stalled provider does,
    until the runtime's first-output bound gives up on them; nothing of them is consumed, so
    the retry replays the same script."""

    def __init__(self, scripts: Sequence[Sequence[ModelEvent]], slow_calls: int) -> None:
        super().__init__(scripts)
        self.slow_left = slow_calls
        self.attempts = 0

    async def stream(
        self, messages: tuple[ModelMessage, ...], tools: tuple[Any, ...], *, deadline: datetime
    ) -> AsyncGenerator[ModelEvent, None]:
        self.attempts += 1
        if self.slow_left:
            self.slow_left -= 1
            await asyncio.Event().wait()  # cancelled by the bound
        async for event in super().stream(messages, tools, deadline=deadline):
            yield event


class Harness:
    def __init__(
        self,
        scripts: Sequence[Sequence[ModelEvent]],
        *,
        limits: Limits | None = None,
        signals: SignalAnalyzer | None = None,
        store: MemoryStore | None = None,
        slow_calls: int = 0,
        on_closed: Callable[[SessionId], Awaitable[None]] | None = None,
        clock: Callable[[], datetime] | None = None,
        model: FakeModel | None = None,
    ):
        self.store = store or MemoryStore()
        self.telemetry = RecordingTelemetry()
        self.model = model or (SlowFirst(scripts, slow_calls) if slow_calls else FakeModel(scripts))
        self.runtime = build_runtime(
            model=self.model,
            store=self.store,
            signals=signals,
            limits=limits,
            telemetry=self.telemetry,
            clock=clock or (lambda: NOW),
            on_closed=on_closed,
        )

    async def open_session(self, language: Language = "es") -> None:
        state = session_state(SESSION).model_copy(update={"language": language})
        await self.store.sessions.create(state, access_hash="")

    async def run(self, text: str, input_id: str = "in-1") -> list[RuntimeEvent]:
        return [event async for event in self.runtime.run_turn(turn(text, input_id))]

    async def journal(self) -> tuple[EventRecord, ...]:
        """The session's journal, read through the store contract."""
        snapshot = await self.store.snapshot(SESSION, versions=STAMP, taken_at=NOW)
        return snapshot.events if snapshot is not None else ()

    async def usage(self) -> tuple[UsageRecord, ...]:
        """What the session used, read through the store contract."""
        snapshot = await self.store.snapshot(SESSION, versions=STAMP, taken_at=NOW)
        return snapshot.usage if snapshot is not None else ()


async def fill_record(h: Harness) -> None:
    """Every requested field captured, as if the candidate had said them all."""
    state = await h.store.sessions.get(SESSION)
    assert state is not None
    async with h.store.transaction() as tx:
        await h.store.sessions.save(
            tx, state.model_copy(update={"candidate": full_record()}), expected_revision=0
        )


def with_slots_offered(*then: list[ModelEvent], date_preference: str | None = None) -> Harness:
    """Turn in-1 offers the slots, as the model does when the candidate asks for an interview;
    the scripts after it are the model's next turns. This model never presents a slot itself
    (KI-06): whatever is read back, the runtime read back."""
    return Harness(
        [[offer_call(date_preference), WANTS_TOOLS], says(""), *then],
        store=MemoryStore(clock=lambda: NOW),
    )


async def slots_offered(h: Harness) -> None:
    """Calendar seeded, brief confirmed, then the offer in turn in-1."""
    await h.open_session()
    await seed_calendar(h.store, CONFIGS, now=NOW)
    await fill_record(h)
    state = await h.store.sessions.get(SESSION)
    assert state is not None
    async with h.store.transaction() as tx:
        await h.store.sessions.save(
            tx,
            state.model_copy(update={"brief_confirmed_revision": state.candidate.revision}),
            expected_revision=state.candidate.revision,
        )
    await h.run("Sí, quiero entrevista.", "in-1")


def with_date_read_back(*then: list[ModelEvent]) -> Harness:
    """Turn in-1 captures the date and the runtime reads it back, as in the hosted call; the
    scripts after it are the model's next turns."""
    return Harness([[DATE_CALL, WANTS_TOOLS], says(""), *then])


async def readback_pending(h: Harness) -> None:
    await h.run("El 2 de noviembre", "in-1")


def tools_started(events: list[RuntimeEvent]) -> list[str]:
    return [e.name for e in events if isinstance(e, ToolStarted)]


async def voice_run(h: Harness, text: str, input_id: str = "v-1") -> list[RuntimeEvent]:
    voice_turn = TurnInput(
        session_id=SESSION, input_id=InputId(input_id), text=text, channel="voice", received_at=NOW
    )
    return [event async for event in h.runtime.run_turn(voice_turn)]


def decision_analyzer(
    *p_switch: float, delay: float = 0, sentiment: str = "neutral"
) -> DecisionSignalAnalyzer:
    """A decision model that answers each turn with this sentiment (neutral unless said), and
    this probability of answering in the other of Spanish and English, read from the session
    language it is asked about."""

    def verdict(p: float) -> Callable[[dict[str, str]], Decision]:
        def answer(state: dict[str, str]) -> Decision:
            current = state["session_language"]
            other = "en" if current == "es" else "es"
            return Decision(
                answers={
                    "sentiment": ChoiceAnswer(choice=sentiment, probabilities={sentiment: 1}),
                    "reply_language": ChoiceAnswer(
                        choice=other if p >= 0.5 else current,
                        probabilities={current: 1 - p, other: p},
                    ),
                },
                model_id="fake-decision",
                input_tokens=300,
                output_tokens=0,
            )

        return answer

    return DecisionSignalAnalyzer(
        FakeDecisionModel([verdict(p) for p in p_switch], delay_seconds=delay)
    )
