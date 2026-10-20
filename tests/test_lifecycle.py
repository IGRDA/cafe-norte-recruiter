"""Lifecycle transitions and the outcome each terminal event implies."""

from datetime import UTC, datetime

import pytest

from cafe_norte.domain.contracts import (
    Booking,
    CandidateRecord,
    Captured,
    ConfigId,
    ConfirmationId,
    Evidence,
    Lifecycle,
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


def test_complete_is_brief_only_without_a_booking_and_reserved_with_one() -> None:
    assert transition(state(), "complete") == Ok(("completed", "brief_only"))
    booking = Booking(
        slot_id=SlotId("slot"),
        config_id=ConfigId("c"),
        starts_at_utc=datetime(2026, 11, 2, 9, tzinfo=UTC),
        confirmation_id=ConfirmationId("k"),
        idempotency_key="k",
        committed_at=datetime(2026, 10, 20, tzinfo=UTC),
    )
    assert transition(state(booking=booking), "complete") == Ok(("completed", "reserved"))


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
