"""Session lifecycle: which transitions are allowed and what outcome they imply."""

from typing import Literal

from cafe_norte.domain.contracts import Lifecycle, Outcome, SessionState
from cafe_norte.domain.result import Result

LifecycleEvent = Literal[
    "pause",  # silence, disconnect, SIGTERM
    "resume",  # authorized resume link
    "complete",  # brief confirmed (with or without booking)
    "stop",  # explicit stop or withdrawn interest
    "abandon",  # time cap or lease expired without resume
    "fail",  # unrecoverable provider or storage failure
]

TRANSITIONS: dict[Lifecycle, frozenset[LifecycleEvent]] = {
    "active": frozenset({"pause", "complete", "stop", "abandon", "fail"}),
    "paused": frozenset({"resume", "abandon", "fail"}),
    "completed": frozenset(),
    "stopped": frozenset(),
    "abandoned": frozenset(),
    "failed": frozenset(),
}


def transition(
    state: SessionState, event: LifecycleEvent
) -> Result[tuple[Lifecycle, Outcome | None], Lifecycle]:
    """Next lifecycle and the outcome a terminal event implies; ``Err`` carries the unchanged
    lifecycle when the event is not allowed from it."""
    raise NotImplementedError
