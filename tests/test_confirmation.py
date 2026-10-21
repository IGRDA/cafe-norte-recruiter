"""Presenting a read-back and interpreting the candidate's answer against it."""

from datetime import UTC, datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st

from cafe_norte.domain.confirmation import (
    assurance,
    invalidated_by_patch,
    present,
    ready_to_confirm,
    respond,
    review,
    start_parts,
)
from cafe_norte.domain.contracts import (
    BriefTarget,
    CandidateFieldName,
    CandidateRecord,
    ConfigId,
    Confirmation,
    ConfirmationId,
    FieldTarget,
    ReviewInParts,
    ReviewOffered,
    ReviewWaived,
    SessionId,
    SessionState,
    TurnId,
)
from cafe_norte.domain.result import Err, Ok

OTHER_FIELDS: tuple[CandidateFieldName, ...] = (
    "name",
    "interest",
    "work_authorization",
    "availability_days",
    "availability_shifts",
    "hours_per_week",
    "experience",
    "contact_phone",
)

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
    survived = invalidated_by_patch(state(phone), 4, changed=("hours_per_week",))
    assert survived is not None and survived.status == "pending"
    assert survived.target == FieldTarget(field="contact_phone", revision=4)  # retargeted
    assert invalidated_by_patch(state(None), 4) is None
    confirmed = phone.model_copy(update={"status": "confirmed"})
    assert invalidated_by_patch(state(confirmed), 4) == confirmed


@given(st.integers(min_value=0, max_value=50), st.sampled_from(OTHER_FIELDS))
def test_a_patch_of_another_field_never_leaves_a_field_read_back_unanswerable(
    revision: int, other: CandidateFieldName
) -> None:
    """The hosted call of 21 October: the date was read back, the experience was saved, and
    the candidate's "sí" could no longer confirm the date (stale revision)."""
    date = present(
        state(revision=revision),
        FieldTarget(field="earliest_start_date", revision=revision),
        "Fecha.",
        T1,
        ConfirmationId("k"),
    ).model_copy(update={"fully_delivered": True})
    survived = invalidated_by_patch(state(date, revision), revision + 1, changed=(other,))
    after = state(survived, revision + 1)
    answered = respond(after, "affirm", T2)
    assert isinstance(answered, Ok) and answered.value.status == "confirmed"


# ---- reviewing a read-back that was cut (D39) ----------------------------------------------

PARTS = 3


def stage(name: str | None, *, part: int = 0, heard: bool = False, at: TurnId = T2) -> Confirmation:
    """The pending brief read-back presented in T1, at the given review stage, set in ``at``."""
    reviewed = {
        None: None,
        "offered": ReviewOffered(turn_id=at),
        "in_parts": ReviewInParts(part=part, parts=PARTS, turn_id=at),
        "waived": ReviewWaived(turn_id=at),
    }[name]
    return pending_brief(delivered=heard).model_copy(update={"review": reviewed})


@pytest.mark.parametrize(
    ("confirmation", "ready"),
    [
        (stage(None, heard=True), True),
        (stage(None, heard=False), False),
        (stage("offered", heard=True), False),
        (stage("in_parts", part=0, heard=True), False),
        (stage("in_parts", part=PARTS - 1, heard=False), False),
        (stage("in_parts", part=PARTS - 1, heard=True), True),
        (stage("waived", heard=False), True),
    ],
)
def test_a_read_back_is_ready_to_confirm_when_heard_whole_reviewed_to_the_end_or_waived(
    confirmation: Confirmation, ready: bool
) -> None:
    assert ready_to_confirm(confirmation) is ready


@pytest.mark.parametrize(
    ("confirmation", "answer", "expected"),
    [
        (stage(None), "affirm", ReviewOffered(turn_id=T3)),
        (stage(None), "skip", ReviewOffered(turn_id=T3)),  # no informed skip before the offer
        (stage("offered"), "affirm", ReviewInParts(part=0, parts=PARTS, turn_id=T3)),
        (stage("offered"), "skip", ReviewWaived(turn_id=T3)),
        (
            stage("in_parts", part=0, heard=True),
            "affirm",
            ReviewInParts(part=1, parts=PARTS, turn_id=T3),
        ),
        (stage("in_parts", part=0, heard=True), "skip", ReviewWaived(turn_id=T3)),
        (stage("in_parts", part=1, heard=False), "affirm", ReviewWaived(turn_id=T3)),  # cut again
        (stage("in_parts", part=1, heard=False), "skip", ReviewWaived(turn_id=T3)),
    ],
)
def test_the_review_moves_one_step_per_answer(
    confirmation: Confirmation, answer: str, expected: object
) -> None:
    moved = review(state(confirmation), answer, T3, parts=PARTS)  # type: ignore[arg-type]
    assert isinstance(moved, Ok) and moved.value.review == expected


def test_a_part_starts_unheard_and_is_acknowledged_by_the_turn_that_says_it() -> None:
    moved = review(state(stage("offered")), "affirm", T3, parts=PARTS)
    assert isinstance(moved, Ok)
    assert moved.value.fully_delivered is False and moved.value.presented_turn_id == T3
    waived = review(state(stage("offered")), "skip", T3, parts=PARTS)
    assert isinstance(waived, Ok) and waived.value.presented_turn_id == T1  # nothing is said


def test_a_heard_read_back_has_nothing_to_review_and_the_review_never_confirms() -> None:
    for answer in ("affirm", "skip"):
        assert review(state(stage(None, heard=True)), answer, T3, parts=PARTS) == Err(
            "already_heard"
        )
        last = stage("in_parts", part=PARTS - 1, heard=True)
        assert review(state(last), answer, T3, parts=PARTS) == Err("already_heard")
        moved = review(state(stage("offered")), answer, T3, parts=PARTS)
        assert isinstance(moved, Ok) and moved.value.status == "pending"


def test_the_review_refuses_what_a_confirmation_refuses_and_one_move_per_turn() -> None:
    assert review(state(None), "affirm", T3, parts=PARTS) == Err("nothing_pending")
    answered = stage(None).model_copy(update={"status": "confirmed"})
    assert review(state(answered), "affirm", T3, parts=PARTS) == Err("already_answered")
    assert review(state(stage(None)), "affirm", T1, parts=PARTS) == Err("same_turn")
    # The offer was made in T2: the candidate has not answered it in T2.
    assert review(state(stage("offered", at=T2)), "affirm", T2, parts=PARTS) == Err("same_turn")


def test_a_cut_read_back_presented_again_goes_straight_to_its_first_part_once() -> None:
    started = start_parts(state(stage(None)), T3, parts=PARTS)
    assert isinstance(started, Ok)
    assert started.value.review == ReviewInParts(part=0, parts=PARTS, turn_id=T3)
    assert started.value.fully_delivered is False and started.value.presented_turn_id == T3
    assert start_parts(state(stage(None, heard=True)), T3, parts=PARTS) == Err("already_heard")
    for reviewed in (stage("offered"), stage("in_parts", heard=True), stage("waived")):
        assert start_parts(state(reviewed), T3, parts=PARTS) == Err("already_reviewed")
    assert start_parts(state(None), T3, parts=PARTS) == Err("nothing_pending")
    assert start_parts(state(stage(None)), T1, parts=PARTS) == Err("same_turn")


def test_respond_confirms_a_reviewed_read_back_and_refuses_one_still_under_review() -> None:
    waived = respond(state(stage("waived")), "affirm", T3)
    assert isinstance(waived, Ok) and waived.value.status == "confirmed"
    under_review = respond(state(stage("in_parts", part=0, heard=True)), "affirm", T3)
    assert under_review == Err("not_delivered")
    offered = respond(state(stage("offered", heard=True)), "affirm", T3)
    assert offered == Err("not_delivered")
    # A denial or a correction lands whatever the stage: the candidate can always say what is wrong.
    denied = respond(state(stage("in_parts", part=1)), "deny", T3)
    assert isinstance(denied, Ok) and denied.value.status == "rejected"


def test_assurance_tells_the_three_ways_of_being_confirmed_apart() -> None:
    assert assurance(stage(None, heard=True)) == "heard"
    assert assurance(stage("in_parts", part=PARTS - 1, heard=True)) == "reviewed"
    assert assurance(stage("waived")) == "waived"


# One candidate: a cut read-back, then any sequence of answers and playbacks.
_ACTIONS = st.sampled_from(["affirm", "skip", "deny", "heard", "cut"])


@given(st.lists(_ACTIONS, max_size=30))
def test_nothing_is_confirmed_without_a_full_hearing_a_review_to_the_end_or_an_informed_skip(
    actions: list[str],
) -> None:
    """Drive the domain like the runtime does: each candidate answer is a new turn; playback
    marks the latest saying heard; a cut leaves it unheard. Check every transition."""
    current = pending_brief(delivered=False)
    for number, action in enumerate(actions):
        turn = TurnId(f"turn-{number + 2}")
        if action == "heard":
            current = current.model_copy(update={"fully_delivered": True})
            continue
        if action == "cut":
            current = current.model_copy(update={"fully_delivered": False})
            continue
        before = current
        if action == "deny":
            result = respond(state(current), "deny", turn)
        elif ready_to_confirm(current):
            result = respond(state(current), "affirm", turn)
        else:
            result = review(state(current), action, turn, parts=PARTS)  # type: ignore[arg-type]
        if isinstance(result, Err):
            continue
        current = result.value
        if current.status != "pending":
            assert current.status == "rejected" or ready_to_confirm(before)
            return
        moved, was = current.review, before.review
        if isinstance(moved, ReviewWaived):
            assert was is not None  # a waiver always follows an offer or a part
        if isinstance(moved, ReviewInParts) and isinstance(was, ReviewInParts):
            assert moved.part == was.part + 1  # parts are never skipped
        if moved is not None and moved != was:
            assert moved.turn_id == turn  # one move per turn, stamped with it
