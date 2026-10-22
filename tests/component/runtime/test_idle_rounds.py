"""Rounds that change nothing."""

from cafe_norte.conversation.contracts import (
    AssistantText,
)
from cafe_norte.model.contracts import (
    ModelText,
)
from tests.support.harness import (
    WANTS_TOOLS,
    Harness,
    name_call,
    says,
)


async def test_an_idle_round_before_anything_was_said_still_lets_the_model_answer() -> None:
    h = Harness(
        [
            [name_call(), WANTS_TOOLS],
            says(""),
            [name_call("c2"), WANTS_TOOLS],
            says("¿Tienes permiso?"),
        ]
    )
    await h.open_session()
    await h.run("Soy Lucía.", "in-1")
    events = await h.run("Lucía, ya te lo dije.", "in-2")
    assert [e.text for e in events if isinstance(e, AssistantText)] == ["¿Tienes permiso?"]
    assert len(h.model.calls) == 4


async def test_a_round_whose_saves_committed_and_question_was_said_is_the_last() -> None:
    """After a committed save and its held question, no additional model round is needed."""
    h = Harness([[ModelText(text="¿Tienes permiso?"), name_call(), WANTS_TOOLS], says("")])
    await h.open_session()
    await h.run("Soy Lucía.")
    assert len(h.model.calls) == 1


async def test_a_tool_whose_call_changed_nothing_is_offered_again_only_next_turn() -> None:
    h = Harness(
        [
            [name_call(), WANTS_TOOLS],
            [name_call("c2"), WANTS_TOOLS],
            says("¿Tienes permiso?"),
            says("Gracias."),
        ]
    )
    await h.open_session()
    await h.run("Soy Lucía.", "in-1")
    await h.run("Sí.", "in-2")
    offered = [{tool.name for tool in tools} for tools in h.model.advertised_tools]
    assert ["update_candidate" in names for names in offered] == [True, True, False, True]
