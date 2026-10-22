"""A model slow to say its first word: the deadline and the retry."""

from cafe_norte.conversation.contracts import (
    AssistantText,
    TurnFailed,
    TurnFinished,
)
from tests.support.harness import (
    FAST_DEADLINE,
    Harness,
    SlowFirst,
    says,
)


async def test_a_round_with_no_output_in_time_is_retried_once() -> None:
    """The hosted call: one follow-up round took over six seconds and the turn failed."""
    h = Harness([says("Vale, apuntado.")], limits=FAST_DEADLINE, slow_calls=1)
    await h.open_session()
    events = await h.run("De lunes a viernes")
    assert isinstance(events[-1], TurnFinished)
    assert [e.text for e in events if isinstance(e, AssistantText)] == ["Vale, apuntado."]
    assert isinstance(h.model, SlowFirst) and h.model.attempts == 2


async def test_two_slow_rounds_fail_the_turn_with_timeout() -> None:
    h = Harness([says("Vale.")], limits=FAST_DEADLINE, slow_calls=2)
    await h.open_session()
    events = await h.run("De lunes a viernes")
    assert isinstance(events[-1], TurnFailed) and events[-1].code == "timeout"
