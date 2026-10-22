"""The model's words in a tool-call round are held until the calls commit (D59): said once
every call succeeded, dropped when one was refused. A data turn then needs one round, not
two, and nothing is announced before it is persisted."""

import json

from cafe_norte.conversation.contracts import AssistantText, ToolFinished
from cafe_norte.model.contracts import ModelText, ToolCall
from tests.support.harness import WANTS_TOOLS, Harness, name_call, says

SEARCH = ToolCall(
    call_id="k1",
    name="search_knowledge",
    arguments_json=json.dumps({"question": "¿Dónde estáis?", "queries": ["dirección del local"]}),
)


async def test_a_question_sent_with_a_save_is_said_once_the_save_commits() -> None:
    h = Harness(
        [[ModelText(text="¿Tienes permiso de trabajo?"), name_call(), WANTS_TOOLS], says("Vale.")]
    )
    await h.open_session()
    events = await h.run("Soy Lucía")
    kinds = [type(e).__name__ for e in events]
    assert kinds.index("ToolFinished") < kinds.index("AssistantText")
    assert [e.text for e in events if isinstance(e, AssistantText)] == [
        "¿Tienes permiso de trabajo?"
    ]
    assert len(h.model.calls) == 1  # the question was asked: no second round


async def test_a_question_sent_with_a_refused_save_is_never_heard() -> None:
    """Live rule: nothing announced before it is persisted. A name the candidate did not say
    is refused; the question that came with it would have been said on a false save."""
    h = Harness(
        [
            [ModelText(text="¿Tienes permiso de trabajo?"), name_call(name="Ane"), WANTS_TOOLS],
            says("¿Cómo te llamas?"),
        ]
    )
    await h.open_session()
    events = await h.run("Soy Lucía")
    refused = next(e for e in events if isinstance(e, ToolFinished))
    assert refused.ok is False
    assert [e.text for e in events if isinstance(e, AssistantText)] == ["¿Cómo te llamas?"]
    dropped = [e for e in h.telemetry.events if e.event == "held_dropped"]
    assert len(dropped) == 1 and dropped[0].payload["sentences"] == 1


async def test_a_question_with_a_lookup_still_gets_its_answer_round() -> None:
    """A lookup's result is something to say; the round after it is not saved."""
    h = Harness(
        [[ModelText(text="Un momento."), SEARCH, WANTS_TOOLS], says("Estamos en Chamberí.")]
    )
    await h.open_session()
    events = await h.run("¿Dónde estáis?")
    assert [e.text for e in events if isinstance(e, AssistantText)] == [
        "Un momento.",
        "Estamos en Chamberí.",
    ]
    assert len(h.model.calls) == 2


async def test_a_plain_answer_is_said_whole_at_the_end_of_its_stream() -> None:
    h = Harness([says("Hola, soy ", "Ana. ¿Cómo te ", "llamas?")])
    await h.open_session()
    events = await h.run("Hola")
    assert [e.text for e in events if isinstance(e, AssistantText)] == [
        "Hola, soy Ana.",
        "¿Cómo te llamas?",
    ]
