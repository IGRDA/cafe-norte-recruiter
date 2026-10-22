"""Handlers for fields and the brief: the domain decides, the store commits, the model is told
what to do next."""

from datetime import date

from cafe_norte.conversation.brief import field_readback, render_brief
from cafe_norte.conversation.contracts import StateUpdated, ToolOutcome
from cafe_norte.conversation.handlers import (
    NEXT_STEP,
)
from cafe_norte.conversation.readback import review_parts
from cafe_norte.domain.candidate import apply_patch
from cafe_norte.domain.contracts import (
    BriefTarget,
    CandidatePatch,
    CandidateRecord,
    FieldTarget,
    ReviewInParts,
    TurnId,
)
from tests.support.builders import CONFIG, EVIDENCE, full_record
from tests.support.tools import World, args, context


async def test_the_brief_is_refused_until_every_requested_field_is_settled() -> None:
    w = await World().open()
    outcome = await w.present(context(), args("present_confirmation", target="brief"))
    assert not outcome.ok and outcome.summary == "brief_not_ready:name"
    assert "name" in outcome.model_text and outcome.spoken == ""
    assert (await w.current()).pending_confirmation is None


async def test_only_phone_and_date_have_field_readbacks() -> None:
    w = await World(full_record()).open()
    outcome = await w.present(context(), args("present_confirmation", target="field", field="name"))
    assert not outcome.ok and outcome.summary == "no_readback_for:name"


async def test_presenting_the_brief_speaks_the_exact_text_that_becomes_pending() -> None:
    w = await World(full_record()).open()
    outcome = await w.present(context(), args("present_confirmation", target="brief"))
    expected = render_brief(full_record(), CONFIG, "es")
    assert outcome.ok and outcome.spoken == expected
    assert "already spoken" in outcome.model_text
    state = await w.current()
    pending = state.pending_confirmation
    assert pending is not None and pending.status == "pending"
    assert pending.target == BriefTarget(revision=1)
    assert pending.presentation_text == expected and pending.fully_delivered is False
    assert isinstance(outcome.events[0], StateUpdated)
    assert outcome.events[0].pending_confirmation == pending


async def test_a_correction_after_the_brief_invalidates_it() -> None:
    w = await World(full_record()).open()
    await w.present(context(), args("present_confirmation", target="brief"))
    await w.deliver()
    outcome = await w.update(
        context("t2"),
        args("update_candidate", patch={"hours_per_week": 25}, evidence_text="son 25 horas"),
    )
    assert outcome.ok
    state = await w.current()
    assert state.candidate.revision == 2
    assert state.pending_confirmation is not None
    assert state.pending_confirmation.status == "invalidated"
    assert "present the brief again" in outcome.model_text


async def test_capturing_a_date_or_phone_speaks_the_read_back_itself() -> None:
    """No model decision in between: the read-back is pending the moment the value is saved."""
    w = await World().open()
    outcome = await w.update(
        context(),
        args(
            "update_candidate",
            patch={"name": "Ane", "earliest_start_date": "2026-10-26"},
            evidence_text="Ane, el lunes que viene",
        ),
    )
    assert outcome.ok
    assert outcome.spoken == field_readback("earliest_start_date", date(2026, 10, 26), "es")
    assert "already spoken" in outcome.model_text
    state = await w.current()
    pending = state.pending_confirmation
    assert pending is not None and pending.status == "pending"
    assert isinstance(pending.target, FieldTarget)
    assert pending.target.field == "earliest_start_date"
    assert outcome.events[0].pending_confirmation == pending  # type: ignore[union-attr]


async def test_resending_a_known_value_changes_nothing_and_points_at_the_pending_answer() -> None:
    """Live: after "sí lo es" the model re-sent the date; it was read back a second time."""
    w = await World().open()
    first = args(
        "update_candidate",
        patch={"earliest_start_date": "2026-11-01"},
        evidence_text="1 de noviembre",
    )
    await w.update(context(), first)
    await w.deliver()
    again = await w.update(context("t2"), first)
    assert again.ok and again.spoken == "" and again.summary == "unchanged"
    assert "confirm_field" in again.model_text
    assert again.idle and "do not call update_candidate again" in again.model_text.lower()
    state = await w.current()
    assert state.candidate.revision == 1
    assert state.pending_confirmation is not None
    assert state.pending_confirmation.status == "pending"
    assert state.pending_confirmation.presented_turn_id == TurnId("t1")


async def test_resending_a_confirmed_value_keeps_it_confirmed() -> None:
    w = await World(full_record()).open()
    await w.present(
        context(), args("present_confirmation", target="field", field="earliest_start_date")
    )
    await w.deliver()
    await w.confirm_field(context("t2"), args("confirm_field", answer="affirm"))
    again = await w.update(
        context("t3"),
        args(
            "update_candidate", patch={"earliest_start_date": "2026-10-26"}, evidence_text="el 26"
        ),
    )
    assert again.ok and again.summary == "unchanged"
    state = await w.current()
    assert state.candidate.earliest_start_date.status == "confirmed"
    assert state.candidate.revision == 1


async def test_presenting_the_same_pending_read_back_again_is_a_no_op() -> None:
    """Live: the model re-presented the date read-back and it was spoken twice."""
    w = await World(full_record()).open()
    first = await w.present(
        context(), args("present_confirmation", target="field", field="earliest_start_date")
    )
    await w.deliver()
    again = await w.present(
        context("t2"), args("present_confirmation", target="field", field="earliest_start_date")
    )
    assert again.ok and again.spoken == "" and again.summary == "already_pending:field"
    assert "confirm_field" in again.model_text
    state = await w.current()
    assert state.pending_confirmation is not None
    assert state.pending_confirmation.presented_turn_id == TurnId("t1")
    assert state.pending_confirmation.presentation_text == first.spoken


async def test_the_brief_waits_for_an_unanswered_field_read_back() -> None:
    w = await World(full_record()).open()
    await w.present(
        context(), args("present_confirmation", target="field", field="earliest_start_date")
    )
    await w.deliver()
    outcome = await w.present(context("t2"), args("present_confirmation", target="brief"))
    assert not outcome.ok and outcome.summary == "readback_pending:earliest_start_date"
    assert "confirm_field" in outcome.model_text


async def test_candidate_done_with_an_unconfirmed_brief_reads_the_brief_again() -> None:
    """Live: the model closed anyway and the session hung open. Instead of a refusal the
    candidate hears the brief and a "sí" closes it properly."""
    w = await World(full_record()).open()
    outcome = await w.end(context(), args("end_session", reason="candidate_done"))
    assert not outcome.ok and outcome.summary == "brief_re_presented"
    assert outcome.spoken == render_brief(full_record(), CONFIG, "es")
    assert "wait" in outcome.model_text.lower()
    state = await w.current()
    assert state.lifecycle == "active"
    assert state.pending_confirmation is not None
    assert state.pending_confirmation.status == "pending"


async def test_a_goodbye_with_fields_missing_ends_the_session_incomplete() -> None:
    """A goodbye ends collection while preserving the facts already recorded."""
    w = await World().open()
    done = await w.end(context(), args("end_session", reason="candidate_done"))
    assert done.ok
    state = await w.current()
    assert (state.lifecycle, state.outcome) == ("stopped", "incomplete")


async def test_a_goodbye_with_the_brief_already_read_ends_the_session() -> None:
    """Live, 22 October: the brief was on the table, every "adiós" read it again and the call
    never ended. The first goodbye reads it once; the next one ends the session."""
    w = await World(full_record()).open()
    first = await w.end(context(), args("end_session", reason="candidate_done"))
    assert not first.ok and first.summary == "brief_re_presented"
    second = await w.end(context("t2"), args("end_session", reason="candidate_done"))
    assert second.ok
    state = await w.current()
    assert (state.lifecycle, state.outcome) == ("stopped", "incomplete")


async def test_candidate_done_needs_the_brief_confirmed_at_the_current_revision() -> None:
    w = await World(full_record()).open()
    refused = await w.end(context(), args("end_session", reason="candidate_done"))
    assert not refused.ok
    await w.present(context(), args("present_confirmation", target="brief"))
    await w.deliver()
    await w.confirm_brief(context("t2"), args("confirm_brief", answer="affirm"))
    done = await w.end(context("t3"), args("end_session", reason="candidate_done"))
    assert done.ok
    assert (await w.current()).outcome == "brief_only"


async def test_a_note_after_the_confirmed_brief_keeps_it_confirmed() -> None:
    w = await World(full_record()).open()
    await w.present(context(), args("present_confirmation", target="brief"))
    await w.deliver()
    await w.confirm_brief(context("t2"), args("confirm_brief", answer="affirm"))
    outcome = await w.update(
        context("t3"),
        args("update_candidate", patch={"note": "quiere entrevista"}, evidence_text="sí"),
    )
    assert outcome.ok and outcome.summary == "captured:note"
    state = await w.current()
    assert state.candidate.revision == 1 and state.candidate.notes == ("quiere entrevista",)
    assert state.pending_confirmation is not None
    assert state.pending_confirmation.status == "confirmed"


async def test_the_interview_answer_after_the_confirmed_brief_leads_to_the_end() -> None:
    """Issue #10: a note saved on a confirmed brief is the interview answer; the model is
    told to end the session, not to ask about the interview again."""
    w = await World(full_record()).open()
    await w.present(context(), args("present_confirmation", target="brief"))
    await w.deliver()
    await w.confirm_brief(context("t2"), args("confirm_brief", answer="affirm"))
    saved = await w.update(
        context("t3"),
        args("update_candidate", patch={"note": "quiere entrevista"}, evidence_text="sí"),
    )
    assert saved.ok and "end_session" in saved.model_text
    assert NEXT_STEP["interview"] not in saved.model_text
    done = await w.end(context("t4"), args("end_session", reason="candidate_done"))
    assert done.ok and done.summary == "ended:completed:brief_only"


async def test_a_read_back_that_was_not_fully_heard_is_gone_over_in_parts() -> None:
    """Presenting an interrupted read-back starts its first part without repeating it whole."""
    w = await World(full_record()).open()
    first = await w.present(context("t1"), args("present_confirmation", target="brief"))
    again = await w.present(context("t2"), args("present_confirmation", target="brief"))
    parts = review_parts(first.spoken, "es")
    assert again.ok and again.summary == f"review:part:1/{len(parts)}"
    assert again.spoken == parts[0]  # never the whole text a second time
    pending = (await w.current()).pending_confirmation
    assert pending is not None and pending.presentation_text == first.spoken
    assert pending.review == ReviewInParts(part=0, parts=len(parts), turn_id=TurnId("t2"))
    assert pending.presented_turn_id == TurnId("t2") and pending.fully_delivered is False
    under_review = await w.present(context("t3"), args("present_confirmation", target="brief"))
    assert under_review.spoken == "" and "review_readback" in under_review.model_text


async def test_not_delivered_tells_the_model_to_pass_the_answer_to_the_review() -> None:
    w = await World(full_record()).open()
    await w.present(context("t1"), args("present_confirmation", target="brief"))
    refused = await w.confirm_brief(context("t2"), args("confirm_brief", answer="affirm"))
    assert not refused.ok and "review_readback" in refused.model_text
    assert "present_confirmation" not in refused.model_text


async def test_the_model_cannot_answer_a_read_back_in_the_turn_it_was_presented() -> None:
    w = await World(full_record()).open()
    await w.present(context("t1"), args("present_confirmation", target="brief"))
    await w.deliver()
    same_turn = await w.confirm_brief(context("t1"), args("confirm_brief", answer="affirm"))
    assert not same_turn.ok and same_turn.summary == "confirmation_refused:same_turn"
    assert "wait" in same_turn.model_text.lower()
    assert same_turn.idle and "end your turn now" in same_turn.model_text.lower()
    assert (await w.current()).pending_confirmation.status == "pending"  # type: ignore[union-attr]


async def test_affirming_a_field_readback_confirms_the_field_without_a_new_revision() -> None:
    w = await World(full_record()).open()
    await w.present(
        context(), args("present_confirmation", target="field", field="earliest_start_date")
    )
    refused = await w.confirm_field(context("t2"), args("confirm_field", answer="affirm"))
    assert not refused.ok and refused.summary == "confirmation_refused:not_delivered"
    await w.deliver()
    outcome = await w.confirm_field(context("t2"), args("confirm_field", answer="affirm"))
    assert outcome.ok
    state = await w.current()
    assert state.candidate.earliest_start_date.status == "confirmed"
    assert state.candidate.revision == 1
    assert state.pending_confirmation is not None
    assert state.pending_confirmation.status == "confirmed"


async def test_denying_the_brief_rejects_it_and_asks_for_the_correction() -> None:
    w = await World(full_record()).open()
    await w.present(context(), args("present_confirmation", target="brief"))
    await w.deliver()
    outcome = await w.confirm_brief(context("t2"), args("confirm_brief", answer="deny"))
    assert outcome.ok and "ask what is wrong" in outcome.model_text
    state = await w.current()
    assert state.pending_confirmation is not None
    assert state.pending_confirmation.status == "rejected"


async def test_affirming_the_brief_invites_questions_before_the_interview() -> None:
    w = await World(full_record()).open()
    await w.present(context(), args("present_confirmation", target="brief"))
    await w.deliver()
    outcome = await w.confirm_brief(context("t2"), args("confirm_brief", answer="affirm"))
    assert outcome.ok and outcome.model_text.endswith(NEXT_STEP["questions"])
    assert (await w.current()).lifecycle == "active"


async def test_end_session_sets_lifecycle_and_outcome_once() -> None:
    w = await World(full_record()).open()
    await w.present(context(), args("present_confirmation", target="brief"))
    await w.deliver()
    await w.confirm_brief(context("t2"), args("confirm_brief", answer="affirm"))
    done = await w.end(context("t3"), args("end_session", reason="candidate_done"))
    assert done.ok and isinstance(done.events[0], StateUpdated)
    state = await w.current()
    assert (state.lifecycle, state.outcome) == ("completed", "brief_only")
    again = await w.end(context("t4"), args("end_session", reason="candidate_done"))
    assert not again.ok and again.summary == "lifecycle_refused:completed"


async def test_not_interested_stops_with_that_outcome() -> None:
    no = apply_patch(CandidateRecord(), CandidatePatch(interest="no"), EVIDENCE)
    w = await World(no).open()
    outcome = await w.end(context(), args("end_session", reason="not_interested"))
    assert outcome.ok
    state = await w.current()
    assert (state.lifecycle, state.outcome) == ("stopped", "not_interested")


def test_tool_outcome_spoken_defaults_to_nothing() -> None:
    assert ToolOutcome(ok=True, model_text="x", summary="y").spoken == ""


async def test_a_confirmed_field_is_not_read_back_again() -> None:
    """Iñaki's call: "That's right." confirmed the date; the model then called confirm_field
    again, was told "Present it again", and the date was read back a second time."""
    w = await World(full_record()).open()
    await w.present(
        context(), args("present_confirmation", target="field", field="earliest_start_date")
    )
    await w.deliver()
    await w.confirm_field(context("t2"), args("confirm_field", answer="affirm"))
    twice = await w.confirm_field(context("t2"), args("confirm_field", answer="affirm"))
    assert not twice.ok and twice.summary == "confirmation_refused:already_answered"
    assert "Present it again" not in twice.model_text
    assert "already confirmed" in twice.model_text
    again = await w.present(
        context("t2"), args("present_confirmation", target="field", field="earliest_start_date")
    )
    assert not again.ok and again.summary == "already_confirmed:earliest_start_date"
    assert again.spoken == "" and "already confirmed" in again.model_text


async def test_a_note_tells_the_model_nobody_will_act_on_it() -> None:
    """Ignacio's call: "¿Quieres que lo deje anotado para que te contacten?" — "Sí, anótalo",
    and the model saved a note. A note reaches no one; the result says so, with the tool that
    does, so the model can correct itself."""
    w = await World().open()
    outcome = await w.update(
        context(),
        args(
            "update_candidate",
            patch={"note": "Dice que es hijo del dueño y le prometieron 15.000 euros."},
            evidence_text="yo soy hijo del dueño",
        ),
    )
    assert outcome.ok
    assert "nobody will contact" in outcome.model_text
    assert "request_human_followup" in outcome.model_text
    named = await w.update(
        context("t2"), args("update_candidate", patch={"name": "Ane"}, evidence_text="Ane")
    )
    assert "nobody will contact" not in named.model_text  # only a note earns it


async def test_a_question_in_the_closing_line_is_answered_before_the_call_ends() -> None:
    """Live: "No, muchas gracias. ¿Tienes alguna otra oferta?" was closed with the question
    unanswered. A stated stop still closes."""
    w = await World(full_record()).open()
    await w.present(context(), args("present_confirmation", target="brief"))
    await w.deliver()
    await w.confirm_brief(context("t2"), args("confirm_brief", answer="affirm"))
    await w.said("t3", "No, muchas gracias. ¿Tienes alguna otra oferta?")
    asked = await w.end(context("t3"), args("end_session", reason="candidate_done"))
    assert not asked.ok and asked.summary == "answer_first"
    assert "search_knowledge" in asked.model_text
    assert (await w.current()).lifecycle == "active"
    stop = await w.end(context("t3"), args("end_session", reason="candidate_stop"))
    assert stop.ok


async def test_a_correction_after_the_brief_reads_back_only_what_changed() -> None:
    """Live: "Sí, pero mi nombre es Princesa Rosmugalda" had the whole summary read again,
        then the review offer. Only the changed sentence is said, with the closing question
    ; it is still a read-back of the whole brief at its new revision."""
    w = await World(full_record()).open()
    await w.present(context(), args("present_confirmation", target="brief"))
    await w.deliver()
    await w.update(
        context("t2"),
        args(
            "update_candidate",
            patch={"name": "Princesa Rosmugalda"},
            evidence_text="mi nombre es Princesa Rosmugalda",
        ),
    )
    again = await w.present(context("t2"), args("present_confirmation", target="brief"))
    assert again.ok and again.spoken == "Te llamas Princesa Rosmugalda. ¿Es todo correcto?"
    await w.deliver()
    confirmed = await w.confirm_brief(context("t3"), args("confirm_brief", answer="affirm"))
    assert confirmed.ok
    state = await w.current()
    assert state.brief_confirmed_revision == state.candidate.revision == 2
