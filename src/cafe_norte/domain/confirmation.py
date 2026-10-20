"""Presenting a read-back and interpreting the candidate's answer to it.

The runtime never decides on its own that "sí" means "book it". It asks this module, which
only accepts an answer against the confirmation that is actually pending, fully delivered and
still targeting the current revision."""

from typing import Literal

from cafe_norte.domain.contracts import (
    Confirmation,
    ConfirmationId,
    ConfirmationTarget,
    SessionState,
    TurnId,
)
from cafe_norte.domain.result import Result

Answer = Literal["affirm", "deny", "correct", "unrelated"]

ConfirmationRefusal = Literal[
    "nothing_pending",
    "not_delivered",
    "stale_revision",
    "wrong_target",
    "already_answered",
]


def present(
    state: SessionState,
    target: ConfirmationTarget,
    presentation_text: str,
    presented_turn_id: TurnId,
    confirmation_id: ConfirmationId,
    *,
    source: Literal["model", "ui"] = "model",
) -> Confirmation:
    """Create the pending confirmation. Any earlier pending one becomes ``invalidated``."""
    raise NotImplementedError


def respond(
    state: SessionState, answer: Answer, response_turn_id: TurnId
) -> Result[Confirmation, ConfirmationRefusal]:
    """Resolve the pending confirmation with the candidate's answer.

    ``affirm`` succeeds only if the confirmation is pending, was fully delivered and its target
    revision is still the record's revision. ``correct`` and ``deny`` mark it rejected.
    ``unrelated`` changes nothing and is reported as ``wrong_target``."""
    raise NotImplementedError


def invalidated_by_patch(state: SessionState, new_revision: int) -> Confirmation | None:
    """The pending confirmation after a fact changed: brief and slot targets referencing an
    older revision become ``invalidated``; a field target for another field survives."""
    raise NotImplementedError
