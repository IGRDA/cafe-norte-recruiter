"""Going over a read-back the candidate cut."""

from cafe_norte.conversation.contracts import StateUpdated
from cafe_norte.conversation.handlers import (
    NEXT_STEP,
)
from cafe_norte.conversation.readback import review_parts
from cafe_norte.domain.contracts import (
    ReviewOffered,
    ReviewWaived,
    TurnId,
)
from tests.support.builders import full_record
from tests.support.tools import SLOT, Interview, World, args, context


async def cut_brief() -> tuple[World, str]:
    """The brief said in t1 and cut by the candidate: not heard to the end."""
    w = await World(full_record()).open()
    said = await w.present(context("t1"), args("present_confirmation", target="brief"))
    return w, said.spoken


async def test_a_yes_over_a_cut_read_back_earns_one_offer_in_the_models_words() -> None:
    w, _ = await cut_brief()
    offered = await w.review(context("t2"), args("review_readback", answer="affirm"))
    assert offered.ok and offered.summary == "review:offered" and offered.spoken == ""
    assert "offer" in offered.model_text and "review_readback" in offered.model_text
    pending = (await w.current()).pending_confirmation
    assert pending is not None and pending.review == ReviewOffered(turn_id=TurnId("t2"))
    assert isinstance(offered.events[0], StateUpdated)


async def test_going_over_it_says_each_part_and_the_yes_to_the_last_confirms() -> None:
    w, text = await cut_brief()
    parts = review_parts(text, "es")
    await w.review(context("t2"), args("review_readback", answer="affirm"))
    for number, part in enumerate(parts, start=1):
        said = await w.review(context(f"t{number + 2}"), args("review_readback", answer="affirm"))
        assert said.ok and said.summary == f"review:part:{number}/{len(parts)}"
        assert said.spoken == part and "already spoken" in said.model_text
        await w.deliver()
    confirmed = await w.review(context("t9"), args("review_readback", answer="affirm"))
    assert confirmed.ok and confirmed.summary == "brief:confirmed"
    state = await w.current()
    assert state.pending_confirmation is not None
    assert state.pending_confirmation.status == "confirmed"
    assert state.brief_confirmed_revision == 1


async def test_carrying_on_after_the_offer_confirms_it_as_waived_in_one_call() -> None:
    w, _ = await cut_brief()
    await w.review(context("t2"), args("review_readback", answer="skip"))  # before: the offer
    waived = await w.review(context("t3"), args("review_readback", answer="skip"))
    assert waived.ok and waived.summary == "brief:confirmed"
    assert NEXT_STEP["questions"] in waived.model_text
    first, last = waived.events[0], waived.events[-1]
    assert isinstance(first, StateUpdated) and isinstance(last, StateUpdated)
    assert first.pending_confirmation is not None
    assert first.pending_confirmation.status == "pending"  # the waiver is saved first
    assert first.pending_confirmation.review == ReviewWaived(turn_id=TurnId("t3"))
    state = await w.current()
    assert state.pending_confirmation is not None
    assert state.pending_confirmation.status == "confirmed"
    assert state.pending_confirmation.review == ReviewWaived(turn_id=TurnId("t3"))


async def test_a_cut_field_read_back_carried_on_confirms_the_field() -> None:
    w = await World(full_record()).open()
    await w.present(
        context("t1"), args("present_confirmation", target="field", field="earliest_start_date")
    )
    await w.review(context("t2"), args("review_readback", answer="affirm"))
    waived = await w.review(context("t3"), args("review_readback", answer="skip"))
    assert waived.ok and waived.summary == "field:confirmed"
    assert (await w.current()).candidate.earliest_start_date.status == "confirmed"


async def test_a_cut_slot_read_back_carried_on_is_booked() -> None:
    w = await (await Interview().ready()).offered()
    await w.present(context("t4"), args("present_confirmation", target="slot", slot_id=SLOT))
    await w.review(context("t5"), args("review_readback", answer="affirm"))
    booked = await w.review(context("t6"), args("review_readback", answer="skip"))
    assert booked.ok and booked.summary == "reserved"
    booking = (await w.current()).booking
    assert booking is not None and booking.slot_id == SLOT


async def test_the_review_refuses_what_the_domain_refuses() -> None:
    w = await World(full_record()).open()
    nothing = await w.review(context("t1"), args("review_readback", answer="affirm"))
    assert not nothing.ok and nothing.summary == "review_refused:nothing_pending"
    await w.present(context("t1"), args("present_confirmation", target="brief"))
    same_turn = await w.review(context("t1"), args("review_readback", answer="affirm"))
    assert not same_turn.ok and same_turn.summary == "review_refused:same_turn"
    assert "wait" in same_turn.model_text.lower()
    await w.review(context("t2"), args("review_readback", answer="affirm"))
    twice = await w.review(context("t2"), args("review_readback", answer="affirm"))
    assert not twice.ok and twice.summary == "review_refused:same_turn"


async def test_reserve_on_a_cut_slot_read_back_points_at_the_review() -> None:
    w = await (await Interview().ready()).offered()
    await w.present(context("t4"), args("present_confirmation", target="slot", slot_id=SLOT))
    refused = await w.reserve(context("t5"), args("reserve_interview", slot_id=SLOT))
    assert refused.summary == "confirmation_refused:not_delivered"
    assert "review_readback" in refused.model_text


async def test_a_save_beside_a_cut_read_back_points_at_the_review() -> None:
    w = await World(full_record()).open()
    await w.present(
        context("t1"), args("present_confirmation", target="field", field="earliest_start_date")
    )
    saved = await w.update(
        context("t2"),
        args("update_candidate", patch={"note": "tiene coche"}, evidence_text="tengo coche"),
    )
    assert saved.ok and "review_readback" in saved.model_text
    assert "confirm_field" not in saved.model_text


async def test_only_a_call_that_changed_nothing_is_idle() -> None:
    """A save, a refusal the model can act on and a first read-back each move the turn on;
    only a repeat of a done save and an answer the candidate has not given yet are idle."""
    w = await World().open()
    saved = await w.update(
        context(), args("update_candidate", patch={"name": "Lucía"}, evidence_text="Lucía")
    )
    refused = await w.update(
        context(),
        args("update_candidate", patch={"hours_per_week": 30}, evidence_text="por la mañana"),
    )
    again = await w.update(
        context(), args("update_candidate", patch={"name": "Lucía"}, evidence_text="Lucía")
    )
    nothing = await w.confirm_field(context(), args("confirm_field", answer="affirm"))
    assert [o.idle for o in (saved, refused, again, nothing)] == [False, False, True, False]


async def test_a_question_during_the_review_is_answered_before_any_part() -> None:
    """Iñaki's call: "Me gustaría saber cuál es la localización exacta." during the offer went
    to review_readback as a yes; part 1 was said and the answer about the place was dropped,
    three turns running."""
    w, _ = await cut_brief()
    await w.review(context("t2"), args("review_readback", answer="affirm"))  # the offer
    await w.said("t3", "Me gustaría saber cuál es la localización exacta.")
    asked = await w.review(context("t3"), args("review_readback", answer="affirm"))
    assert not asked.ok and asked.summary == "review_refused:question"
    assert asked.spoken == "" and "search_knowledge" in asked.model_text
    pending = (await w.current()).pending_confirmation
    assert pending is not None and pending.review == ReviewOffered(turn_id=TurnId("t2"))
