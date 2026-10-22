"""Plain answers to a read-back, resolved by the runtime (D35)."""

from typing import Literal

from cafe_norte.conversation.contracts import (
    AssistantText,
    RuntimeEvent,
    ToolStarted,
    TurnInput,
    UiAnswer,
)
from cafe_norte.domain.contracts import (
    ConfirmationId,
    InputId,
)
from tests.support.builders import NOW, SESSION
from tests.support.harness import (
    Harness,
    readback_pending,
    says,
    with_date_read_back,
)


async def test_a_plain_yes_confirms_the_heard_read_back_even_if_the_model_forgets() -> None:
    """The hosted call: "Sí, es correcto" answered with no confirm_field; the runtime now
    resolves it before the model, which then simply goes on."""
    h = with_date_read_back(says("Perfecto. ¿Qué experiencia tienes?"))
    await h.open_session()
    await readback_pending(h)
    events = await h.run("Sí, es correcto.", "in-2")
    state = await h.store.sessions.get(SESSION)
    assert state is not None and state.candidate.earliest_start_date.status == "confirmed"
    assert state.pending_confirmation is not None
    assert state.pending_confirmation.status == "confirmed"
    names = [e.name for e in events if isinstance(e, ToolStarted)]
    assert names == ["confirm_field"]
    facts = h.model.calls[-1][0].content
    assert "readback_answered" in facts


async def test_a_plain_no_rejects_it_and_the_model_asks_what_is_wrong() -> None:
    h = with_date_read_back(says("¿Qué fecha es?"))
    await h.open_session()
    await readback_pending(h)
    await h.run("No, no es correcto.", "in-2")
    state = await h.store.sessions.get(SESSION)
    assert state is not None and state.pending_confirmation is not None
    assert state.pending_confirmation.status == "rejected"


async def test_a_yes_with_more_words_is_left_to_the_model() -> None:
    h = with_date_read_back(says("Vale."))
    await h.open_session()
    await readback_pending(h)
    await h.run("Sí, pero el teléfono es otro", "in-2")
    state = await h.store.sessions.get(SESSION)
    assert state is not None and state.pending_confirmation is not None
    assert state.pending_confirmation.status == "pending"


def button(
    answer: Literal["affirm", "deny"], confirmation_id: ConfirmationId, input_id: str = "in-2"
) -> TurnInput:
    """What the page's Sí / No posts: no words, an explicit answer to one read-back."""
    return TurnInput(
        session_id=SESSION,
        input_id=InputId(input_id),
        text="",
        channel="text",
        received_at=NOW,
        ui_answer=UiAnswer(confirmation_id=confirmation_id, answer=answer),
    )


async def pending_id(h: Harness) -> ConfirmationId:
    state = await h.store.sessions.get(SESSION)
    assert state is not None and state.pending_confirmation is not None
    return state.pending_confirmation.confirmation_id


async def test_the_yes_button_confirms_through_the_same_tool_as_a_spoken_yes() -> None:
    h = with_date_read_back(says("Perfecto. ¿Qué experiencia tienes?"))
    await h.open_session()
    await readback_pending(h)
    events = await _run(h, button("affirm", await pending_id(h)))
    state = await h.store.sessions.get(SESSION)
    assert state is not None and state.candidate.earliest_start_date.status == "confirmed"
    assert state.pending_confirmation is not None
    assert state.pending_confirmation.status == "confirmed"
    assert [e.name for e in events if isinstance(e, ToolStarted)] == ["confirm_field"]
    users = [t for t in await h.store.turns.recent(SESSION, 10) if t.role == "user"]
    assert users[-1].text == "Sí"  # the transcript shows what the candidate pressed
    assert "readback_answered" in h.model.calls[-1][0].content


async def test_the_no_button_rejects_it_in_the_session_language() -> None:
    h = with_date_read_back(says("Understood. What is the right date?"))
    await h.open_session("en")
    await readback_pending(h)
    events = await _run(h, button("deny", await pending_id(h)))
    state = await h.store.sessions.get(SESSION)
    assert state is not None and state.pending_confirmation is not None
    assert state.pending_confirmation.status == "rejected"
    assert [e.name for e in events if isinstance(e, ToolStarted)] == ["confirm_field"]
    users = [t for t in await h.store.turns.recent(SESSION, 10) if t.role == "user"]
    assert users[-1].text == "No"


async def test_a_button_for_another_read_back_changes_nothing() -> None:
    h = with_date_read_back(says("Vale."))
    await h.open_session()
    await readback_pending(h)
    events = await _run(h, button("affirm", ConfirmationId("an-older-one")))
    state = await h.store.sessions.get(SESSION)
    assert state is not None and state.pending_confirmation is not None
    assert state.pending_confirmation.status == "pending"
    assert not [e for e in events if isinstance(e, ToolStarted)]


async def test_the_button_on_a_read_back_the_voice_has_not_finished_says_it_again() -> None:
    """A page only mirrors the call (D39): pressing Sí on a card whose read-back was cut is a
    yes to what was not heard, like a spoken one. It no longer counts as reading it (D38). A
    one-sentence read-back has no offer: it is said again once (D59)."""
    h = with_date_read_back(says("Perdona. ¿Lo repasamos o seguimos?"))
    await h.open_session()
    await readback_pending(h)
    state = await h.store.sessions.get(SESSION)
    assert state is not None and state.pending_confirmation is not None
    heard_nothing = state.pending_confirmation.model_copy(update={"fully_delivered": False})
    async with h.store.transaction() as tx:
        await h.store.sessions.save(
            tx,
            state.model_copy(update={"pending_confirmation": heard_nothing}),
            expected_revision=state.candidate.revision,
        )
    events = await _run(h, button("affirm", heard_nothing.confirmation_id))
    assert [e.name for e in events if isinstance(e, ToolStarted)] == ["review_readback"]
    state = await h.store.sessions.get(SESSION)
    assert state is not None and state.pending_confirmation is not None
    assert state.pending_confirmation.status == "pending"
    assert state.pending_confirmation.review is not None
    assert state.pending_confirmation.review.stage == "in_parts"
    assert [e.text for e in events if isinstance(e, AssistantText)] == [
        "He apuntado que podrías empezar el lunes 2 de noviembre de 2026.",
        "¿Está bien?",
    ]


async def _run(h: Harness, turn_input: TurnInput) -> list[RuntimeEvent]:
    return [event async for event in h.runtime.run_turn(turn_input)]


async def test_a_turn_on_a_paused_session_makes_it_active_again() -> None:
    h = Harness([says("Aquí sigo.")])
    await h.open_session()
    await h.runtime.end(SESSION, "shutdown")
    paused = await h.store.sessions.get(SESSION)
    assert paused is not None and paused.lifecycle == "paused"
    await h.run("Hola, sigo aquí", "in-1")
    state = await h.store.sessions.get(SESSION)
    assert state is not None and state.lifecycle == "active"
