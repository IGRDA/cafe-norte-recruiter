"""Prompt building and the sentence splitting a streamed answer goes through."""

from hypothesis import given
from hypothesis import strategies as st

from cafe_norte.conversation.prompt import (
    clean_sentence,
    conversation_tail,
    offer_facts,
    sentences,
    split_sentences,
    tool_message,
)
from cafe_norte.domain.calendar import interview_slots
from cafe_norte.domain.contracts import OfferedSlot, SlotOffer
from cafe_norte.model.contracts import ModelMessage
from tests.support.builders import CONFIG, NOW, session_state


def test_sentences_split_at_an_opening_mark_or_capital_without_a_space() -> None:
    done, rest = split_sentences("¿Tienes permiso?¿Qué días puedes?(nota) Sí. Y más")
    assert done == ["¿Tienes permiso?", "¿Qué días puedes?", "(nota) Sí."]
    assert rest == "Y más"
    # The model sometimes writes the candidate's answer right after its own question.
    done, rest = split_sentences("¿Te interesa el puesto?Sí, me interesa.Él también. 3.5 horas")
    assert done == ["¿Te interesa el puesto?", "Sí, me interesa.", "Él también."]
    assert rest == "3.5 horas"


@given(st.text(alphabet="Hola. ¿Qué tal?¡Sí! (nota) 3.5 horas…\n", max_size=60), st.data())
def test_any_chunking_of_a_stream_says_the_same_sentences_as_the_whole_text(
    text: str, data: st.DataObject
) -> None:
    """How the runtime reads a stream: split what has come, keep the rest for the next chunk."""
    cuts = sorted(data.draw(st.lists(st.integers(0, len(text)), max_size=6)))
    chunks = [text[a:b] for a, b in zip([0, *cuts], [*cuts, len(text)], strict=True)]

    said: list[str] = []
    rest = ""
    for chunk in chunks:
        done, rest = split_sentences(rest + chunk)
        said += done
    tail = clean_sentence(rest)

    assert said + ([tail] if tail else []) == sentences(text)


@given(st.text(max_size=60))
def test_a_clean_sentence_is_already_clean(text: str) -> None:
    once = clean_sentence(text)
    assert clean_sentence(once) == once


def message(role: str, content: str) -> ModelMessage:
    return ModelMessage(role=role, content=content)


def test_the_conversation_tail_keeps_the_latest_messages_within_its_budget() -> None:
    messages = [
        message("system", "x" * 5000),
        message("user", "primero " + "a" * 50),
        message("assistant", "segundo " + "b" * 50),
        message("user", "tercero"),
    ]
    assert conversation_tail(messages, budget=40) == "user: tercero"
    assert conversation_tail(messages, budget=10_000).splitlines()[0].startswith("user: primero")
    assert "system" not in conversation_tail(messages, budget=10_000)


def test_the_latest_message_is_kept_even_when_it_alone_exceeds_the_budget() -> None:
    assert conversation_tail([message("user", "z" * 100)], budget=10) == "user: " + "z" * 100


def test_a_tool_result_says_what_was_already_said_this_turn_so_the_model_goes_on() -> None:
    told = tool_message("Saved: name.", ["¿Cómo te llamas?"])

    assert told.startswith("Saved: name. Already said to the candidate this turn: ¿Cómo te")
    assert "Do not repeat or rephrase it" in told
    assert tool_message("Saved: name.", []) == "Saved: name."  # nothing said yet: as it is


def test_the_offer_is_in_the_facts_by_number_and_time_never_by_id() -> None:
    """The model offers the times itself and picks one by number (D56)."""
    slots = tuple(
        OfferedSlot(slot_id=s.slot_id, starts_at_utc=s.starts_at_utc)
        for s in interview_slots(CONFIG, after=NOW)[:2]
    )
    base = session_state()
    state = base.model_copy(
        update={
            "slot_offer": SlotOffer(slots=slots),
            "brief_confirmed_revision": base.candidate.revision,
        }
    )
    assert offer_facts(state, CONFIG) == [
        {"n": 1, "when": "martes 20 de octubre de 2026 a las 17:00"},
        {"n": 2, "when": "miércoles 21 de octubre de 2026 a las 10:30"},
    ]
    assert offer_facts(state.model_copy(update={"slot_offer": None}), CONFIG) is None
    unsettled = state.model_copy(update={"brief_confirmed_revision": None})
    assert offer_facts(unsettled, CONFIG) is None  # a correction voids the brief and the offer
