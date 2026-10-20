"""Presenting a read-back and interpreting the candidate's answer to it.

The runtime never decides on its own that "sí" means "book it". It asks this module, which
only accepts an answer against the confirmation that is actually pending, fully delivered and
still targeting the current revision."""

from collections.abc import Sequence
from typing import Literal

from cafe_norte.domain.contracts import (
    CandidateFieldName,
    Confirmation,
    ConfirmationId,
    ConfirmationTarget,
    FieldTarget,
    SessionState,
    TurnId,
)
from cafe_norte.domain.result import Err, Ok, Result

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
    """Create the pending confirmation. The caller stores it as ``pending_confirmation``, which
    replaces any earlier pending one (that one is thereby ``invalidated``)."""
    return Confirmation(
        confirmation_id=confirmation_id,
        target=target,
        presentation_text=presentation_text,
        presented_turn_id=presented_turn_id,
        source=source,
    )


def respond(
    state: SessionState, answer: Answer, response_turn_id: TurnId
) -> Result[Confirmation, ConfirmationRefusal]:
    """Resolve the pending confirmation with the candidate's answer.

    ``affirm`` succeeds only if the confirmation is pending, was fully delivered and its target
    revision is still the record's revision. ``correct`` and ``deny`` mark it rejected.
    ``unrelated`` changes nothing and is reported as ``wrong_target``."""
    pending = state.pending_confirmation
    if pending is None:
        return Err("nothing_pending")
    if pending.status != "pending":
        return Err("already_answered")
    if answer == "unrelated":
        return Err("wrong_target")
    if answer == "affirm":
        if not pending.fully_delivered:
            return Err("not_delivered")
        if _target_revision(pending.target) != state.candidate.revision:
            return Err("stale_revision")
        status: Literal["confirmed", "rejected"] = "confirmed"
    else:
        status = "rejected"
    return Ok(pending.model_copy(update={"status": status, "response_turn_id": response_turn_id}))


def invalidated_by_patch(
    state: SessionState,
    new_revision: int,
    changed: Sequence[CandidateFieldName] | None = None,
) -> Confirmation | None:
    """The pending confirmation after a fact changed: brief and slot targets referencing an
    older revision become ``invalidated``; a field target survives only when ``changed`` names
    other fields than its own. Answered confirmations are left as they are."""
    pending = state.pending_confirmation
    if pending is None or pending.status != "pending":
        return pending
    if isinstance(pending.target, FieldTarget):
        if changed is not None and pending.target.field not in changed:
            return pending
    elif _target_revision(pending.target) == new_revision:
        return pending
    return pending.model_copy(update={"status": "invalidated"})


def _target_revision(target: ConfirmationTarget) -> int:
    if isinstance(target, FieldTarget):
        return target.revision
    return target.revision if hasattr(target, "revision") else target.brief_revision
