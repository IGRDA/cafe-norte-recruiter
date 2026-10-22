"""Structured events of a turn."""

from cafe_norte.conversation.contracts import (
    TurnFailed,
)
from cafe_norte.conversation.runtime import Limits
from cafe_norte.model.contracts import (
    ModelText,
)
from cafe_norte.model.fake import FakeModel
from cafe_norte.observability.contracts import StructuredEvent
from tests.support.builders import NOW, SESSION
from tests.support.harness import (
    FAST_DEADLINE,
    STOP,
    WANTS_TOOLS,
    Harness,
    name_call,
    says,
)


def named(h: Harness, name: str) -> list[StructuredEvent]:
    return [event for event in h.telemetry.events if event.event == name]


async def test_a_failed_turn_emits_turn_failed_keyed_by_session_and_turn() -> None:
    always_late = FakeModel([], delay_seconds=0.2, fallback=says("tarde"))
    h = Harness([], limits=Limits(llm_first_output_seconds=0.05), model=always_late)
    await h.open_session()
    events = await h.run("Hola")
    failed_turn = events[-1]
    assert isinstance(failed_turn, TurnFailed)
    (event,) = named(h, "turn_failed")
    assert (event.severity, event.session_id, event.turn_id) == (
        "WARNING",
        SESSION,
        failed_turn.turn_id,
    )
    assert event.payload["code"] == "timeout"
    assert event.at == NOW


async def test_a_silent_round_emits_one_event_and_the_retry_is_timed() -> None:
    h = Harness([says("Vale, apuntado.")], limits=FAST_DEADLINE, slow_calls=1)
    await h.open_session()
    await h.run("De lunes a viernes")
    (silent,) = named(h, "model_round_silent")
    assert silent.severity == "WARNING" and silent.payload == {"attempt": 1, "bound_seconds": 0.05}
    (round_,) = named(h, "model_round")
    assert round_.severity == "INFO"
    assert set(round_.payload) == {"attempt", "first_output_ms", "total_ms"}
    assert round_.payload["attempt"] == 2
    assert 0 <= round_.payload["first_output_ms"] <= round_.payload["total_ms"]


async def test_two_silent_rounds_emit_one_silent_event_then_the_failure() -> None:
    h = Harness([says("Vale.")], limits=FAST_DEADLINE, slow_calls=2)
    await h.open_session()
    await h.run("De lunes a viernes")
    assert len(named(h, "model_round_silent")) == 1
    assert [e.payload["code"] for e in named(h, "turn_failed")] == ["timeout"]
    assert named(h, "model_round") == []  # no round ever produced output


async def test_every_model_round_of_a_turn_is_timed() -> None:
    h = Harness([[name_call(), WANTS_TOOLS], says("Hola.")])
    await h.open_session()
    await h.run("Soy Lucía")
    rounds = named(h, "model_round")
    assert [r.payload["attempt"] for r in rounds] == [1, 1]
    assert all(r.session_id == SESSION for r in rounds)


async def test_a_cut_answer_emits_answer_cut_with_the_limit() -> None:
    junk = [ModelText(text="(Esperando respuesta)") for _ in range(200)]
    h = Harness(
        [[ModelText(text="¿Tienes permiso de trabajo? "), *junk, STOP]],
        limits=Limits(max_answer_characters=100),
    )
    await h.open_session()
    await h.run("Maialen")
    (cut,) = named(h, "answer_cut")
    assert cut.severity == "WARNING" and cut.payload == {"limit_characters": 100}


async def test_no_event_carries_what_the_candidate_or_ana_said() -> None:
    h = Harness([[name_call(name="Maialen"), WANTS_TOOLS], says("Encantada, Maialen.")])
    await h.open_session()
    await h.run("Soy Maialen")
    assert h.telemetry.events
    dumped = " ".join(event.model_dump_json() for event in h.telemetry.events)
    assert "Maialen" not in dumped and "Encantada" not in dumped
