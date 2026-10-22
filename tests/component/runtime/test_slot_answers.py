"""Choosing a slot, resolved by the runtime (D41)."""

from cafe_norte.conversation import prompts
from cafe_norte.conversation.contracts import (
    AssistantText,
)
from cafe_norte.domain import confirmation
from cafe_norte.domain.contracts import (
    ConfirmationId,
    FieldTarget,
    SlotId,
    SlotTarget,
    TurnId,
)
from tests.support.builders import SESSION
from tests.support.harness import (
    FRI_17,
    FRI_1030,
    TUE_17,
    WED_1030,
    Harness,
    says,
    slots_offered,
    tools_started,
    with_slots_offered,
)


async def pending_slot(h: Harness) -> SlotId | None:
    state = await h.store.sessions.get(SESSION)
    pending = state.pending_confirmation if state is not None else None
    if pending is None or pending.status != "pending" or not isinstance(pending.target, SlotTarget):
        return None
    return pending.target.slot_id


async def test_an_ordinal_reads_that_slot_back_without_the_model() -> None:
    h = with_slots_offered(says(""))
    await slots_offered(h)
    events = await h.run("El primero.", "in-2")
    assert tools_started(events) == ["present_confirmation"]
    assert await pending_slot(h) == TUE_17
    said = [e.text for e in events if isinstance(e, AssistantText)]
    assert said[0].startswith("He apuntado la entrevista en Café Norte Chamberí el martes 20")
    assert said[-1] == "¿Te la reservo?"
    assert '"slot_choice": "The read-back was already spoken' in h.model.calls[-1][0].content


async def test_the_slot_the_runtime_read_back_is_booked_by_the_plain_yes() -> None:
    h = with_slots_offered(says(""), says("Reservado."))
    await slots_offered(h)
    await h.run("El miércoles a las diez y media.", "in-2")
    await h.run("Sí.", "in-3")
    state = await h.store.sessions.get(SESSION)
    assert state is not None and state.booking is not None
    assert state.booking.slot_id == WED_1030


async def test_another_choice_replaces_the_slot_read_back() -> None:
    h = with_slots_offered(says(""), says(""))
    await slots_offered(h)
    await h.run("El primero.", "in-2")
    events = await h.run("Mejor el segundo.", "in-3")
    assert tools_started(events) == ["present_confirmation"]
    assert await pending_slot(h) == WED_1030


async def test_a_refusal_and_words_without_a_slot_are_left_to_the_model() -> None:
    h = with_slots_offered(says("¿Qué día te vendría mejor?"), says("Está en Chamberí."))
    await slots_offered(h)
    assert tools_started(await h.run("No, ninguno me va bien.", "in-2")) == []
    assert tools_started(await h.run("¿Dónde está la tienda?", "in-3")) == []
    assert await pending_slot(h) is None


async def test_before_any_offer_a_day_is_the_models() -> None:
    h = Harness([says("¿Te gustaría tener una entrevista?")])
    await h.open_session()
    assert tools_started(await h.run("El viernes.")) == []


async def test_a_pending_field_read_back_keeps_the_slot_matcher_out() -> None:
    h = with_slots_offered(says("¿Es correcto el teléfono?"))
    await slots_offered(h)
    state = await h.store.sessions.get(SESSION)
    assert state is not None
    field = FieldTarget(field="contact_phone", revision=state.candidate.revision)
    pending = confirmation.present(
        state, field, "¿Es correcto?", TurnId("in-1"), ConfirmationId("phone")
    )
    async with h.store.transaction() as tx:
        await h.store.sessions.save(
            tx,
            state.model_copy(update={"pending_confirmation": pending}),
            expected_revision=state.candidate.revision,
        )
    assert tools_started(await h.run("El primero.", "in-2")) == []


async def shortlist(h: Harness) -> tuple[SlotId, ...]:
    state = await h.store.sessions.get(SESSION)
    assert state is not None and state.slot_offer is not None
    return state.slot_offer.shortlist


async def offered_ids(h: Harness) -> list[SlotId]:
    state = await h.store.sessions.get(SESSION)
    assert state is not None and state.slot_offer is not None
    return [slot.slot_id for slot in state.slot_offer.slots]


async def test_a_day_with_two_slots_asks_which_and_the_time_then_picks_one() -> None:
    """The hosted call's "El viernes." when two Friday slots were offered."""
    h = with_slots_offered(
        says("¿A las 10:30 o a las 17:00?"), says(""), date_preference="2026-10-23"
    )
    await slots_offered(h)
    events = await h.run("El viernes.", "in-2")
    assert tools_started(events) == [] and await pending_slot(h) is None
    assert await shortlist(h) == (FRI_1030, FRI_17)
    facts = h.model.calls[-1][0].content
    assert "slot_choice" in facts and "viernes 23 de octubre de 2026 a las 10:30" in facts
    assert "viernes 23 de octubre de 2026 a las 17:00" in facts
    await h.run("A las diez y media.", "in-3")
    assert await pending_slot(h) == FRI_1030


async def test_the_shortlist_narrows_an_answer_that_alone_would_be_ambiguous() -> None:
    """Offered Tuesday 17:00, Wednesday 10:30 and 17:00: after "el miércoles", "a las cinco"
    means Wednesday's, although Tuesday also has one at five."""
    h = with_slots_offered(says("¿A qué hora?"), says(""))
    await slots_offered(h)
    await h.run("El miércoles.", "in-2")
    await h.run("A las cinco.", "in-3")
    assert await pending_slot(h) == SlotId("chamberi_barista_v1-2026-10-21-1700")


async def test_a_day_not_offered_is_offered_again_for_that_day_by_the_runtime() -> None:
    h = with_slots_offered(says(""))
    await slots_offered(h)
    events = await h.run("¿Y el viernes?", "in-2")
    assert tools_started(events) == ["list_interview_slots"]
    assert await offered_ids(h) == [FRI_1030, FRI_17]
    said = " ".join(e.text for e in events if isinstance(e, AssistantText))
    assert "viernes 23 de octubre de 2026 a las 10:30" in said
    state = await h.store.sessions.get(SESSION)
    assert state is not None and state.schedule_intent is not None
    assert state.schedule_intent.text == "Sí, quiero entrevista."
    assert '"slot_choice": "Offered, in this order' in h.model.calls[-1][0].content


async def test_a_time_not_offered_offers_the_same_slots_again() -> None:
    h = with_slots_offered(says(""))
    await slots_offered(h)
    before = await offered_ids(h)
    events = await h.run("A las ocho.", "in-2")
    assert tools_started(events) == ["list_interview_slots"]
    assert await offered_ids(h) == before


async def booking_of(h: Harness) -> SlotId | None:
    state = await h.store.sessions.get(SESSION)
    assert state is not None
    return None if state.booking is None else state.booking.slot_id


async def test_a_yes_with_the_slot_restated_reserves_it() -> None:
    """ "Exacto, sí, el martes a las cinco" to "¿Te la reservo?": more than a plain yes, but
    the slot it names is the one read back."""
    h = with_slots_offered(says(""), says("Reservado."))
    await slots_offered(h)
    await h.run("El primero.", "in-2")
    events = await h.run("Exacto, sí, el martes a las cinco.", "in-3")
    assert tools_started(events) == ["reserve_interview"]
    assert await booking_of(h) == TUE_17


async def test_a_farewell_after_the_booking_completes_the_session_without_the_model() -> None:
    """Live S01/S02 (22 October 2026): after booking, the model said goodbye back to every
    goodbye and never called end_session, so the session stayed active (D46)."""
    h = with_slots_offered(says(""), says("Reservado."))
    await slots_offered(h)
    await h.run("El primero.", "in-2")
    await h.run("Sí.", "in-3")
    assert await booking_of(h) == TUE_17
    calls = len(h.model.calls)
    events = await h.run("¡Hasta luego, Ana!", "in-4")
    assert tools_started(events) == ["end_session"]
    state = await h.store.sessions.get(SESSION)
    assert state is not None
    assert (state.lifecycle, state.outcome) == ("completed", "reserved")
    said = " ".join(e.text for e in events if isinstance(e, AssistantText))
    assert said == prompts.table("controls", "es")["goodbye"]
    assert len(h.model.calls) == calls  # the model is not asked


async def test_a_farewell_before_any_booking_is_the_models() -> None:
    h = Harness([says("¿Seguro? Aún no hemos reservado la entrevista.")])
    await h.open_session()
    events = await h.run("Adiós.")
    assert tools_started(events) == [] and len(h.model.calls) == 1


async def test_the_slot_restated_without_a_yes_is_not_a_booking() -> None:
    h = with_slots_offered(says(""), says("¿Te la reservo, entonces?"))
    await slots_offered(h)
    await h.run("El primero.", "in-2")
    events = await h.run("El martes a las cinco.", "in-3")
    assert tools_started(events) == []  # the model's to read; it asks again here
    assert await booking_of(h) is None and await pending_slot(h) == TUE_17


async def test_a_yes_with_another_slot_reads_that_one_back_instead() -> None:
    h = with_slots_offered(says(""), says(""))
    await slots_offered(h)
    await h.run("El primero.", "in-2")
    events = await h.run("Sí, mejor el segundo.", "in-3")
    assert tools_started(events) == ["present_confirmation"]
    assert await booking_of(h) is None and await pending_slot(h) == WED_1030


async def test_a_question_after_the_offer_is_answered_by_the_model() -> None:
    """ "Treinta" is not the 30th: the runtime neither offers again nor reads a slot back, so
    the model's answer is said."""
    h = with_slots_offered(says("Unos treinta minutos. ¿Qué hueco prefieres?"))
    await slots_offered(h)
    events = await h.run("¿La entrevista dura treinta minutos?", "in-2")
    assert tools_started(events) == []
    said = [e.text for e in events if isinstance(e, AssistantText)]
    assert said == ["Unos treinta minutos.", "¿Qué hueco prefieres?"]
