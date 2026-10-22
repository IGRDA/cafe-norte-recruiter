"""The candidate's answer to the slot offer, decided from values alone: which tool the
words call, a shortlist to ask about, or nothing (the model's). The runtime only runs it."""

from cafe_norte.conversation.slot_answer import Shortlist, heard_read_back_of, slot_answer
from cafe_norte.domain.calendar import interview_slots
from cafe_norte.domain.confirmation import present
from cafe_norte.domain.contracts import (
    Booking,
    ConfirmationId,
    FieldTarget,
    OfferedSlot,
    SessionState,
    SlotId,
    SlotOffer,
    SlotTarget,
    TurnId,
)
from tests.support.builders import CONFIG, EVIDENCE, NOW, session_state

# Tuesday 20 October 2026, 10:00 UTC: the first three slots are Tue 17:00, Wed 10:30, Wed 17:00.
OFFERED = tuple(
    OfferedSlot(slot_id=s.slot_id, starts_at_utc=s.starts_at_utc)
    for s in interview_slots(CONFIG, after=NOW)[:3]
)
TUE_17, WED_1030, WED_17 = (slot.slot_id for slot in OFFERED)
ASKED = "Sí, quiero entrevista."
EARLIER, TURN = TurnId("t1"), TurnId("t2")  # the read-back's turn, and the answer's


def offered(**update: object) -> SessionState:
    """Brief confirmed, the candidate asked for an interview, and three slots offered."""
    intent = EVIDENCE.model_copy(update={"text": ASKED})
    return session_state().model_copy(
        update={"slot_offer": SlotOffer(slots=OFFERED), "schedule_intent": intent, **update}
    )


def read_back(
    state: SessionState, slot_id: SlotId, *, heard: bool = True, said_in: TurnId = EARLIER
) -> SessionState:
    target = SlotTarget(slot_id=slot_id, brief_revision=state.candidate.revision)
    pending = present(state, target, "¿Te la reservo?", said_in, ConfirmationId("c"))
    pending = pending.model_copy(update={"fully_delivered": heard})
    return state.model_copy(update={"pending_confirmation": pending})


def answer(state: SessionState, text: str, *, by_button: bool = False) -> object:
    return slot_answer(
        state, text, by_button=by_button, turn_id=TURN, configuration=CONFIG, now=NOW
    )


def test_an_ordinal_reads_that_slot_back() -> None:
    assert answer(offered(), "El primero.") == (
        "present_confirmation",
        {"target": "slot", "slot_id": TUE_17},
    )


def test_a_day_and_time_read_that_slot_back() -> None:
    assert answer(offered(), "El miércoles a las diez y media.") == (
        "present_confirmation",
        {"target": "slot", "slot_id": WED_1030},
    )


def test_a_day_with_two_slots_is_a_shortlist_naming_both() -> None:
    choice = answer(offered(), "El miércoles.")

    assert isinstance(choice, Shortlist)
    assert choice.slot_ids == (WED_1030, WED_17)
    assert (  # numbered by their place in the offer, as the model was given them
        "(2: miércoles 21 de octubre de 2026 a las 10:30; "
        "3: miércoles 21 de octubre de 2026 a las 17:00)"
    ) in choice.note


def test_the_shortlist_narrows_an_answer_that_alone_would_be_ambiguous() -> None:
    """After "el miércoles", "a las cinco" means Wednesday's, although Tuesday has one too."""
    narrowed = offered(slot_offer=SlotOffer(slots=OFFERED, shortlist=(WED_1030, WED_17)))

    assert answer(narrowed, "A las cinco.") == (
        "present_confirmation",
        {"target": "slot", "slot_id": WED_17},
    )


def test_a_day_not_offered_offers_again_for_that_day_with_the_original_words() -> None:
    assert answer(offered(), "¿Y el viernes?") == (
        "list_interview_slots",
        {"evidence_text": ASKED, "date_preference": "2026-10-23"},
    )


def test_before_the_candidate_asks_for_an_interview_nothing_is_decided() -> None:
    """The offer is made with the brief, before any time was said: live, "La última."
    to another question booked a time the candidate never heard. The first choice is the
    model's, with the candidate's words."""
    assert answer(offered(schedule_intent=None), "La última.") is None
    assert answer(offered(schedule_intent=None), "¿Y el viernes?") is None


def test_words_that_name_no_day_are_the_models_which_has_the_options() -> None:
    """A time or a month with nothing on offer is not offered again: the same list said
    again is the loop of 22 October. The model says what there is."""
    assert answer(offered(), "A las ocho.") is None
    assert answer(offered(), "El martes de noviembre.") is None


def test_a_yes_with_the_slot_read_back_and_heard_reserves_it() -> None:
    state = read_back(offered(), TUE_17)

    assert answer(state, "Exacto, sí, el martes a las cinco.") == (
        "reserve_interview",
        {"slot_id": TUE_17},
    )


def test_a_read_back_said_in_this_very_turn_is_read_back_again_not_reserved() -> None:
    same_turn = read_back(offered(), TUE_17, said_in=TURN)

    assert answer(same_turn, "Sí, el martes a las cinco.") == (
        "present_confirmation",
        {"target": "slot", "slot_id": TUE_17},
    )


def test_the_slot_restated_without_a_yes_is_the_models() -> None:
    assert answer(read_back(offered(), TUE_17), "El martes a las cinco.") is None


def test_a_yes_with_another_slot_reads_that_one_back_instead() -> None:
    assert answer(read_back(offered(), TUE_17), "Sí, mejor el segundo.") == (
        "present_confirmation",
        {"target": "slot", "slot_id": WED_1030},
    )


def test_a_read_back_not_yet_heard_is_chosen_again_not_reserved() -> None:
    state = read_back(offered(), TUE_17, heard=False)

    assert answer(state, "Sí, el martes a las cinco.") == (
        "present_confirmation",
        {"target": "slot", "slot_id": TUE_17},
    )


def test_words_that_are_not_a_choice_are_the_models() -> None:
    # "Treinta" is not the 30th: the live question after the offer is the model's to answer.
    questions = ("¿Dónde está la tienda?", "¿La entrevista dura treinta minutos?")
    for text in ("No, ninguno me va bien.", *questions):
        assert answer(offered(), text) is None, text


def test_nothing_is_decided_without_an_open_offer() -> None:
    field = FieldTarget(field="contact_phone", revision=0)
    waiting = offered().model_copy(
        update={
            "pending_confirmation": present(
                offered(), field, "¿Es correcto?", TurnId("t1"), ConfirmationId("phone")
            )
        }
    )
    booking = Booking(
        slot_id=TUE_17,
        config_id=CONFIG.config_id,
        starts_at_utc=OFFERED[0].starts_at_utc,
        confirmation_id=ConfirmationId("c"),
        idempotency_key="k",
        committed_at=NOW,
    )
    closed = [
        session_state(),  # nothing offered yet
        offered(slot_offer=SlotOffer(slots=())),
        offered(booking=booking),
        offered(lifecycle="paused"),
        waiting,  # a field read-back waits for its own answer
    ]
    for state in closed:
        assert answer(state, "El primero.") is None
    assert answer(offered(), "El primero.", by_button=True) is None  # a button answers a read-back


def test_a_read_back_counts_as_heard_only_when_said_earlier_and_heard_to_the_end() -> None:
    state = read_back(offered(), TUE_17)

    assert heard_read_back_of(state, TUE_17, TURN)
    assert not heard_read_back_of(state, WED_1030, TURN)
    assert not heard_read_back_of(state, TUE_17, EARLIER)  # the turn that said it
    assert not heard_read_back_of(read_back(offered(), TUE_17, heard=False), TUE_17, TURN)
