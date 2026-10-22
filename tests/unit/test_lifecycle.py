"""Lifecycle transitions and the outcome each terminal event implies."""

from datetime import UTC, datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st

from cafe_norte.domain.contracts import (
    Booking,
    CandidateRecord,
    Captured,
    ConfigId,
    ConfirmationId,
    Evidence,
    Lifecycle,
    ReviewFlag,
    SessionId,
    SessionState,
    SlotId,
    TurnId,
)
from cafe_norte.domain.lifecycle import TRANSITIONS, LifecycleEvent, is_terminal, transition
from cafe_norte.domain.result import Err, Ok


def state(lifecycle: Lifecycle = "active", **extra: object) -> SessionState:
    return SessionState(
        session_id=SessionId("s"),
        config_id=ConfigId("c"),
        config_version="1",
        language="es",
        channel="text",
        created_at=datetime(2026, 10, 20, tzinfo=UTC),
        lifecycle=lifecycle,
        **extra,
    )


@pytest.mark.parametrize("lifecycle", list(TRANSITIONS))
@pytest.mark.parametrize("event", ["pause", "resume", "complete", "stop", "abandon", "fail"])
def test_only_table_transitions_are_allowed(lifecycle: Lifecycle, event: LifecycleEvent) -> None:
    result = transition(state(lifecycle), event)
    if event in TRANSITIONS[lifecycle]:
        assert isinstance(result, Ok)
    else:
        assert result == Err(lifecycle)


BOOKING = Booking(
    slot_id=SlotId("slot"),
    config_id=ConfigId("c"),
    starts_at_utc=datetime(2026, 11, 2, 9, tzinfo=UTC),
    confirmation_id=ConfirmationId("k"),
    idempotency_key="k",
    committed_at=datetime(2026, 10, 20, tzinfo=UTC),
)
KINDS = ["work_authorization", "human_followup", "unsupported_question", "other"]


def test_complete_is_brief_only_without_a_booking_and_reserved_with_one() -> None:
    assert transition(state(), "complete") == Ok(("completed", "brief_only"))
    assert transition(state(booking=BOOKING), "complete") == Ok(("completed", "reserved"))


def test_stop_is_not_interested_only_when_interest_was_stated_as_no() -> None:
    evidence = Evidence(source_turn_id=TurnId("t"), text="no me interesa")
    no = CandidateRecord(interest=Captured[str](value="no", evidence=evidence))
    assert transition(state(candidate=no), "stop") == Ok(("stopped", "not_interested"))
    assert transition(state(), "stop") == Ok(("stopped", "incomplete"))


def test_pause_and_resume_keep_the_outcome_and_are_not_terminal() -> None:
    paused = transition(state(), "pause")
    assert paused == Ok(("paused", None))
    assert transition(state("paused"), "resume") == Ok(("active", None))
    assert transition(state("paused"), "abandon") == Ok(("abandoned", "incomplete"))
    assert not is_terminal(state("paused")) and is_terminal(state("completed"))


FOLLOWUP = (ReviewFlag(kind="human_followup", turn_id=TurnId("t"), note="quiere una persona"),)


def test_an_early_end_with_a_follow_up_is_human_followup_requested() -> None:
    asked = state(review_flags=FOLLOWUP)
    assert transition(asked, "stop") == Ok(("stopped", "human_followup_requested"))
    assert transition(asked, "abandon") == Ok(("abandoned", "human_followup_requested"))
    assert transition(asked, "fail") == Ok(("failed", "human_followup_requested"))
    other = (ReviewFlag(kind="work_authorization", turn_id=TurnId("t"), note="no"),)
    assert transition(state(review_flags=other), "stop") == Ok(("stopped", "incomplete"))


def test_withdrawn_interest_outranks_a_follow_up() -> None:
    evidence = Evidence(source_turn_id=TurnId("t"), text="no me interesa")
    no = CandidateRecord(interest=Captured[str](value="no", evidence=evidence))
    assert transition(state(candidate=no, review_flags=FOLLOWUP), "stop") == Ok(
        ("stopped", "not_interested")
    )


@given(st.lists(st.sampled_from(KINDS), max_size=4), st.booleans())
def test_completing_never_yields_human_followup_requested(kinds: list[str], booked: bool) -> None:
    flags = tuple(ReviewFlag.model_validate({"kind": k, "turn_id": "t", "note": ""}) for k in kinds)
    done = state(review_flags=flags, booking=BOOKING if booked else None)
    assert transition(done, "complete") == Ok(("completed", "reserved" if booked else "brief_only"))
