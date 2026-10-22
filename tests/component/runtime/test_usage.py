"""Usage: a generation with no report is estimated, usage measured outside a turn (D44)."""

from cafe_norte.conversation.contracts import (
    AssistantText,
)
from cafe_norte.conversation.runtime import Limits
from cafe_norte.domain.contracts import (
    SessionId,
)
from cafe_norte.model.contracts import (
    ModelText,
    ModelUsage,
)
from cafe_norte.observability.contracts import UsageRecord
from tests.support.builders import SESSION
from tests.support.harness import (
    FAST_DEADLINE,
    STOP,
    Harness,
    says,
    turn,
)


async def estimated(h: Harness) -> list[tuple[str, float]]:
    return [(u.unit_detail, u.quantity) for u in await h.usage() if u.estimated]


async def test_a_generation_closed_by_a_barge_in_is_estimated_from_its_characters() -> None:
    h = Harness([says("Hola. ", "Te cuento algo. ", "¿Y tú?")])
    await h.open_session()
    stream = h.runtime.run_turn(turn("Hola"))
    async for event in stream:
        if isinstance(event, AssistantText):
            break
    await stream.aclose()
    (input_tokens, output_tokens) = await estimated(h)
    assert input_tokens[0] == "fake:input" and input_tokens[1] > 100  # the system prompt
    # The whole answer was read before its first sentence was said (D59): all three count.
    assert output_tokens == ("fake:output", 7)


async def test_a_cut_runaway_answer_is_estimated() -> None:
    junk = [ModelText(text="(Esperando respuesta)") for _ in range(200)]
    h = Harness(
        [[ModelText(text="¿Tienes permiso de trabajo? "), *junk, STOP]],
        limits=Limits(max_answer_characters=100),
    )
    await h.open_session()
    await h.run("Maialen")
    assert [detail for detail, _ in await estimated(h)] == ["fake:input", "fake:output"]


async def test_a_silent_attempt_and_its_retry_are_each_estimated() -> None:
    h = Harness([says("Vale, apuntado.")], limits=FAST_DEADLINE, slow_calls=1)
    await h.open_session()
    await h.run("De lunes a viernes")
    records = await estimated(h)
    silent, retried = records[:2], records[2:]
    assert silent[1] == ("fake:output", 0) and retried[1] == ("fake:output", 4)


async def test_a_round_the_provider_reported_is_not_estimated() -> None:
    usage = ModelUsage(input_tokens=120, output_tokens=14, model_id="fake")
    h = Harness([[ModelText(text="Hola."), usage, STOP]])
    await h.open_session()
    await h.run("Hola")
    assert await estimated(h) == [] and len(await h.usage()) == 2


def speech_usage() -> UsageRecord:
    return UsageRecord(
        session_id=SESSION,
        turn_id=None,
        kind="stt_seconds",
        quantity=95.5,
        unit_detail="nova-3",
        estimated=False,
    )


async def test_usage_recorded_after_the_session_ended_stores_the_export_again() -> None:
    closed: list[SessionId] = []

    async def on_closed(session_id: SessionId) -> None:
        closed.append(session_id)

    h = Harness([], on_closed=on_closed)
    await h.open_session()
    await h.runtime.end(SESSION, "stop")
    await h.runtime.settle()
    await h.runtime.record_usage(SESSION, [speech_usage()])
    await h.runtime.settle()
    assert await h.usage() == (speech_usage(),)
    assert closed == [SESSION, SESSION]


async def test_usage_recorded_while_the_session_is_open_is_only_stored() -> None:
    closed: list[SessionId] = []

    async def on_closed(session_id: SessionId) -> None:
        closed.append(session_id)

    h = Harness([], on_closed=on_closed)
    await h.open_session()
    await h.runtime.record_usage(SESSION, [speech_usage()])
    await h.runtime.settle()
    assert await h.usage() == (speech_usage(),) and closed == []
