"""Sentences the system says through the runtime, journaled."""

from cafe_norte.conversation.contracts import (
    TurnStarted,
)
from tests.support.builders import SESSION
from tests.support.harness import (
    Harness,
    says,
)


async def test_say_journals_a_fixed_sentence_as_its_own_turn() -> None:
    h = Harness([])
    await h.open_session()
    events = [e async for e in h.runtime.say(SESSION, "¿Sigues ahí?")]
    assert [type(e).__name__ for e in events] == ["TurnStarted", "AssistantText", "TurnFinished"]
    last = (await h.store.turns.recent(SESSION, 1))[0]
    assert (last.role, last.text) == ("assistant", "¿Sigues ahí?")


async def test_an_aside_is_journaled_under_the_running_turn() -> None:
    h = Harness([says("Hola.")])
    await h.open_session()
    events = await h.run("Hola")
    turn_id = next(e.turn_id for e in events if isinstance(e, TurnStarted))
    await h.runtime.aside(turn_id, "Un momento.")
    last = h.store.events.all(SESSION)[-1]
    assert last.kind == "assistant_text" and last.turn_id == turn_id
    assert "Un momento." in last.payload_json
