"""Presenting a read-back and interpreting the candidate's answer against it."""

from datetime import UTC, datetime

from cafe_norte.domain.confirmation import invalidated_by_patch, present, respond
from cafe_norte.domain.contracts import (
    BriefTarget,
    CandidateRecord,
    ConfigId,
    Confirmation,
    ConfirmationId,
    FieldTarget,
    SessionId,
    SessionState,
    TurnId,
)
from cafe_norte.domain.result import Err, Ok

T1, T2, T3 = TurnId("t1"), TurnId("t2"), TurnId("t3")


def state(pending: Confirmation | None = None, revision: int = 3) -> SessionState:
    return SessionState(
        session_id=SessionId("s"),
        config_id=ConfigId("c"),
        config_version="1",
        language="es",
        channel="text",
        created_at=datetime(2026, 10, 20, tzinfo=UTC),
        candidate=CandidateRecord(revision=revision),
        pending_confirmation=pending,
    )


def pending_brief(revision: int = 3, *, delivered: bool = True) -> Confirmation:
    return present(
        state(revision=revision),
        BriefTarget(revision=revision),
        "Resumen.",
        T1,
        ConfirmationId("k1"),
    ).model_copy(update={"fully_delivered": delivered})


def test_present_creates_a_pending_undelivered_confirmation() -> None:
    confirmation = present(state(), BriefTarget(revision=3), "Resumen.", T1, ConfirmationId("k1"))
    assert confirmation.status == "pending" and confirmation.fully_delivered is False
    assert confirmation.presentation_text == "Resumen." and confirmation.source == "model"
    assert confirmation.presented_turn_id == T1 and confirmation.response_turn_id is None


def test_affirm_confirms_only_a_delivered_pending_confirmation_at_the_current_revision() -> None:
    ok = respond(state(pending_brief()), "affirm", T2)
    assert isinstance(ok, Ok)
    assert ok.value.status == "confirmed" and ok.value.response_turn_id == T2

    assert respond(state(None), "affirm", T2) == Err("nothing_pending")
    assert respond(state(pending_brief(delivered=False)), "affirm", T2) == Err("not_delivered")
    stale = state(pending_brief(revision=2), revision=3)
    assert respond(stale, "affirm", T2) == Err("stale_revision")
    answered = pending_brief().model_copy(update={"status": "confirmed", "response_turn_id": T2})
    assert respond(state(answered), "affirm", T3) == Err("already_answered")


def test_a_confirmation_cannot_be_answered_in_the_turn_that_presented_it() -> None:
    """Live: the model affirmed its own read-back before the candidate spoke."""
    assert respond(state(pending_brief()), "affirm", T1) == Err("same_turn")
    assert respond(state(pending_brief()), "deny", T1) == Err("same_turn")


def test_deny_and_correct_reject_and_unrelated_changes_nothing() -> None:
    for answer in ("deny", "correct"):
        result = respond(state(pending_brief()), answer, T2)
        assert isinstance(result, Ok) and result.value.status == "rejected"
    assert respond(state(pending_brief()), "unrelated", T2) == Err("wrong_target")
    # An undelivered read-back can still be denied: the candidate interrupted it.
    denied = respond(state(pending_brief(delivered=False)), "deny", T2)
    assert isinstance(denied, Ok) and denied.value.status == "rejected"


def test_a_patch_invalidates_the_brief_and_the_same_field_but_not_another_field() -> None:
    brief = state(pending_brief(revision=3), revision=3)
    invalid = invalidated_by_patch(brief, 4)
    assert invalid is not None and invalid.status == "invalidated"

    phone = present(
        state(),
        FieldTarget(field="contact_phone", revision=3),
        "Teléfono.",
        T1,
        ConfirmationId("k2"),
    )
    same = invalidated_by_patch(state(phone), 4)
    assert same is not None and same.status == "invalidated"
    assert invalidated_by_patch(state(phone), 4, changed=("hours_per_week",)) == phone
    assert invalidated_by_patch(state(None), 4) is None
    confirmed = phone.model_copy(update={"status": "confirmed"})
    assert invalidated_by_patch(state(confirmed), 4) == confirmed
