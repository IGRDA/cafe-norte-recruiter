"""Session lifecycle: which transitions are allowed and what outcome they imply."""

from typing import Literal

from cafe_norte.domain.contracts import Lifecycle, Outcome, SessionState
from cafe_norte.domain.fields import value_of
from cafe_norte.domain.result import Err, Ok, Result

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

NEXT: dict[LifecycleEvent, Lifecycle] = {
    "pause": "paused",
    "resume": "active",
    "complete": "completed",
    "stop": "stopped",
    "abandon": "abandoned",
    "fail": "failed",
}

TERMINAL: frozenset[Lifecycle] = frozenset({"completed", "stopped", "abandoned", "failed"})


def transition(
    state: SessionState, event: LifecycleEvent
) -> Result[tuple[Lifecycle, Outcome | None], Lifecycle]:
    """Next lifecycle and the outcome a terminal event implies; ``Err`` carries the unchanged
    lifecycle when the event is not allowed from it.

    Outcomes: ``complete`` keeps a committed booking's ``reserved``, otherwise ``brief_only``;
    ``stop`` is ``not_interested`` when interest is ``no``, else ``incomplete``; ``abandon``
    and ``fail`` are ``incomplete``; non-terminal events keep the current outcome."""
    if event not in TRANSITIONS[state.lifecycle]:
        return Err(state.lifecycle)
    next_lifecycle = NEXT[event]
    if next_lifecycle not in TERMINAL:
        return Ok((next_lifecycle, state.outcome))
    outcome: Outcome
    if event == "complete":
        outcome = "reserved" if state.booking is not None else "brief_only"
    elif event == "stop" and value_of(state.candidate.interest) == "no":
        outcome = "not_interested"
    else:
        outcome = "incomplete"
    return Ok((next_lifecycle, outcome))


def is_terminal(state: SessionState) -> bool:
    return state.lifecycle in TERMINAL
