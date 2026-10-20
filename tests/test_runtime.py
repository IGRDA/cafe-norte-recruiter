"""Behaviour of ``Runtime.run_turn`` against the fake model and the memory store."""

import json
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime

import pytest

from cafe_norte.conversation.contracts import (
    AssistantText,
    RuntimeEvent,
    StateUpdated,
    ToolFinished,
    TurnFailed,
    TurnFinished,
    TurnInput,
    TurnStarted,
)
from cafe_norte.conversation.handlers import UpdateCandidateHandler
from cafe_norte.conversation.registry import ToolRegistry
from cafe_norte.conversation.runtime import Limits, Runtime
from cafe_norte.domain.configuration import load_configurations
from cafe_norte.domain.contracts import ConfigId, InputId, SessionId, SessionState
from cafe_norte.knowledge.fake import FakeRetriever
from cafe_norte.model.contracts import (
    ModelError,
    ModelEvent,
    ModelFinished,
    ModelMessage,
    ModelText,
    ToolCall,
    ToolSchema,
)
from cafe_norte.model.fake import FakeModel
from cafe_norte.persistence.memory import MemoryStore
from tests.support import CONFIG_DIR

SESSION = SessionId("s1")
NOW = datetime(2026, 10, 20, 10, 0, tzinfo=UTC)
STOP = ModelFinished(reason="stop")
WANTS_TOOLS = ModelFinished(reason="tool_calls")


def says(*parts: str) -> list[ModelEvent]:
    return [*(ModelText(text=p) for p in parts), STOP]


def name_call(call_id: str = "c1", name: str = "Lucía") -> ToolCall:
    return ToolCall(
        call_id=call_id,
        name="update_candidate",
        arguments_json=json.dumps({"patch": {"name": name}, "evidence_text": f"Soy {name}"}),
    )


def turn(text: str, input_id: str = "in-1") -> TurnInput:
    return TurnInput(
        session_id=SESSION,
        input_id=InputId(input_id),
        text=text,
        channel="text",
        received_at=NOW,
    )


class Harness:
    def __init__(self, scripts: Sequence[Sequence[ModelEvent]], *, limits: Limits | None = None):
        self.store = MemoryStore()
        configurations = load_configurations(CONFIG_DIR)
        self.model = FakeModel(scripts)
        handler = UpdateCandidateHandler(store=self.store, configurations=configurations)
        self.runtime = Runtime(
            model=self.model,
            tools=ToolRegistry({"update_candidate": handler}),
            retriever=FakeRetriever(),
            store=self.store,
            configurations=configurations,
            signals=None,
            limits=limits or Limits(),
            owner="test",
            clock=lambda: NOW,
        )

    async def open_session(self) -> None:
        await self.store.sessions.create(
            SessionState(
                session_id=SESSION,
                config_id=ConfigId("chamberi_barista_v1"),
                config_version="1",
                language="es",
                channel="text",
            ),
            access_hash="",
        )

    async def run(self, text: str, input_id: str = "in-1") -> list[RuntimeEvent]:
        return [event async for event in self.runtime.run_turn(turn(text, input_id))]


async def test_the_candidate_state_is_committed_before_the_state_update_is_yielded() -> None:
    h = Harness([[name_call(), WANTS_TOOLS], says("Hola.")])
    await h.open_session()
    revisions_seen: list[int] = []
    async for event in h.runtime.run_turn(turn("Soy Lucía")):
        if isinstance(event, StateUpdated):
            state = await h.store.sessions.get(SESSION)
            assert state is not None
            revisions_seen.append(state.candidate.revision)
    assert revisions_seen == [1]


async def test_sentences_are_streamed_as_they_complete_and_the_tail_is_flushed() -> None:
    h = Harness([says("Hola, soy ", "Ana. ¿Cómo te ", "llamas?")])
    await h.open_session()
    events = await h.run("Hola")
    assert [e.text for e in events if isinstance(e, AssistantText)] == [
        "Hola, soy Ana.",
        "¿Cómo te llamas?",
    ]
    assert isinstance(events[-1], TurnFinished)


async def test_every_event_is_journaled_with_increasing_seq_before_it_is_yielded() -> None:
    h = Harness([says("Hola.")])
    await h.open_session()
    seen = 0
    async for _ in h.runtime.run_turn(turn("Hola")):
        seen += 1
        assert h.store.events.last_seq(SESSION) == seen


async def test_the_model_sees_history_state_and_only_registered_tools() -> None:
    h = Harness([[name_call(), WANTS_TOOLS], says("Encantada."), says("Sí.")])
    await h.open_session()
    await h.run("Soy Lucía", "in-1")
    await h.run("¿Me oyes?", "in-2")
    third = h.model.calls[2]
    assert [m.role for m in third] == ["system", "user", "assistant", "user"]
    assert third[2].content == "Encantada."
    assert '"candidate_known_values": {"name": "Lucía"}' in third[0].content
    assert '"name": "captured"' in third[0].content
    assert '"status"' not in third[0].content.split("candidate_known_values")[1].split("}")[0]
    assert [t.name for t in h.model.advertised_tools[0]] == ["update_candidate"]


async def test_a_domain_refusal_goes_back_to_the_model_and_writes_nothing() -> None:
    bad = ToolCall(
        call_id="c1",
        name="update_candidate",
        arguments_json=json.dumps(
            {"patch": {"earliest_start_date": "2020-01-01"}, "evidence_text": "en 2020"}
        ),
    )
    h = Harness([[bad, WANTS_TOOLS], says("¿Cuándo?")])
    await h.open_session()
    events = await h.run("Empecé en 2020")
    finished = [e for e in events if isinstance(e, ToolFinished)]
    assert finished[0].ok is False
    assert finished[0].summary == "validation_failed:earliest_start_date:past_date"
    assert not any(isinstance(e, StateUpdated) for e in events)
    state = await h.store.sessions.get(SESSION)
    assert state is not None and state.candidate.revision == 0
    assert "Rejected field earliest_start_date: past_date" in h.model.calls[1][-1].content


async def test_tool_rounds_are_bounded() -> None:
    forever: list[list[ModelEvent]] = [[name_call(f"c{i}"), WANTS_TOOLS] for i in range(5)]
    h = Harness(forever, limits=Limits(max_tool_rounds=2))
    await h.open_session()
    events = await h.run("Soy Lucía")
    assert len([e for e in events if isinstance(e, ToolFinished)]) == 2
    assert isinstance(events[-1], TurnFailed) and events[-1].code == "limit_exceeded"
    assert len(h.model.calls) == 3


async def test_a_duplicate_input_id_fails_once_with_conflict_and_calls_no_model() -> None:
    h = Harness([says("Hola.")])
    await h.open_session()
    await h.run("Hola", "in-1")
    events = await h.run("Hola otra vez", "in-1")
    assert [type(e) for e in events] == [TurnFailed]
    assert isinstance(events[0], TurnFailed) and events[0].code == "conflict"
    assert len(h.model.calls) == 1


class BrokenModel:
    model_id = "broken"

    async def stream(
        self,
        messages: tuple[ModelMessage, ...],
        tools: tuple[ToolSchema, ...],
        *,
        deadline: datetime,
    ) -> AsyncIterator[ModelEvent]:
        raise ModelError("secret provider detail", code="provider_unavailable")
        yield  # pragma: no cover


async def test_a_model_error_becomes_a_turn_failed_with_public_text_only() -> None:
    h = Harness([])
    h.runtime._model = BrokenModel()
    await h.open_session()
    events = await h.run("Hola")
    assert isinstance(events[0], TurnStarted)
    failed = events[-1]
    assert isinstance(failed, TurnFailed)
    assert failed.code == "provider_unavailable"
    assert "secret" not in failed.message


async def test_a_slow_first_token_fails_with_timeout() -> None:
    h = Harness([], limits=Limits(llm_first_output_seconds=0.05))
    h.runtime._model = FakeModel([says("tarde")], delay_seconds=0.2)
    await h.open_session()
    events = await h.run("Hola")
    assert isinstance(events[-1], TurnFailed) and events[-1].code == "timeout"


async def test_an_unknown_session_fails_with_not_found() -> None:
    h = Harness([])
    events = await h.run("Hola")
    assert isinstance(events[0], TurnFailed) and events[0].code == "not_found"


@pytest.mark.parametrize("text", ["", "   "])
async def test_blank_model_output_still_finishes_the_turn(text: str) -> None:
    h = Harness([says(text)])
    await h.open_session()
    events = await h.run("Hola")
    assert not any(isinstance(e, AssistantText) for e in events)
    assert isinstance(events[-1], TurnFinished)
