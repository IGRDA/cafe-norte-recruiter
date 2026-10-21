"""``active_increment``: what one turn adds to a session's active seconds."""

from datetime import UTC, datetime, timedelta

from cafe_norte.domain.session_time import IDLE_GAP_SECONDS, active_increment

T0 = datetime(2026, 10, 20, 10, 0, tzinfo=UTC)


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def test_a_turn_adds_the_gap_since_the_last_answer_and_its_own_duration() -> None:
    assert active_increment(at(0), at(10), at(14)) == 14.0


def test_a_long_pause_counts_only_up_to_the_idle_cap() -> None:
    assert active_increment(at(0), at(500), at(503)) == IDLE_GAP_SECONDS + 3


def test_the_first_turn_has_no_gap() -> None:
    assert active_increment(None, at(10), at(14)) == 4.0


def test_a_clock_that_runs_backwards_never_subtracts() -> None:
    assert active_increment(at(20), at(10), at(5)) == 0.0
