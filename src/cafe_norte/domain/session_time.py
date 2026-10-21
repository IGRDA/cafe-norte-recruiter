"""Active conversation time: what one turn adds to ``SessionState.active_seconds``."""

from datetime import datetime

IDLE_GAP_SECONDS = 30.0  # at most this much of the pause before a turn counts as conversation


def active_increment(
    previous_end: datetime | None,
    received_at: datetime,
    finished_at: datetime,
    *,
    idle_cap: float = IDLE_GAP_SECONDS,
) -> float:
    """The candidate's thinking and speaking before the turn (the gap since Ana last finished,
    capped so a pause or a resume does not eat the budget) plus the turn itself. Never
    negative, whatever the clocks say."""
    gap = 0.0
    if previous_end is not None:
        gap = min(max((received_at - previous_end).total_seconds(), 0.0), idle_cap)
    return gap + max((finished_at - received_at).total_seconds(), 0.0)
