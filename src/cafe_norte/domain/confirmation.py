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
    ReviewInParts,
    ReviewOffered,
    ReviewWaived,
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
    "same_turn",  # answered in the turn that presented it: only the candidate may answer
    "nothing_to_review",  # heard whole, reviewed to the end or waived: confirm it instead
    "already_reviewed",  # the review has started: it is not started again
]
ReviewAnswer = Literal["affirm", "skip"]
Assurance = Literal["heard", "reviewed", "waived"]


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

    ``affirm`` succeeds only if the confirmation is pending, is ready to confirm (heard, reviewed
    or waived) and its target revision is still the record's revision. ``correct`` and ``deny``
    mark it rejected.
    ``unrelated`` changes nothing and is reported as ``wrong_target``. Any answer in the same
    turn that presented it is ``same_turn``: the candidate has not spoken yet."""
    opened = _open(state, response_turn_id)
    if isinstance(opened, Err):
        return opened
    pending = opened.value
    if answer == "unrelated":
        return Err("wrong_target")
    if answer == "affirm":
        if not ready_to_confirm(pending):
            return Err("not_delivered")
        if _target_revision(pending.target) != state.candidate.revision:
            return Err("stale_revision")
        status: Literal["confirmed", "rejected"] = "confirmed"
    else:
        status = "rejected"
    return Ok(pending.model_copy(update={"status": status, "response_turn_id": response_turn_id}))


def ready_to_confirm(confirmation: Confirmation) -> bool:
    """Heard whole; or gone over to the last part and heard; or the candidate waived the review.
    Anything else (cut, offered, a part still to hear) cannot be confirmed."""
    stage = confirmation.review
    if stage is None:
        return confirmation.fully_delivered
    if isinstance(stage, ReviewInParts):
        return confirmation.fully_delivered and stage.part == stage.parts - 1
    return isinstance(stage, ReviewWaived)


def advance_review(
    state: SessionState, answer: ReviewAnswer, turn_id: TurnId, *, parts: int
) -> Result[Confirmation, ConfirmationRefusal]:
    """The candidate's answer to a read-back that is not ready: a yes goes one step further into
    the review, "carry on" waives it. One step per answer, one answer per turn.

    | now | affirm | skip |
    | said, not heard, one part | that part, said again | waived |
    | said, not heard | offered | offered (no skip before the offer) |
    | offered | first part | waived |
    | part, not the last (heard or cut by the yes) | next part | waived |
    | last part cut | waived | waived |

    A yes over a part answers that part's check, so the review moves on; a yes over the last
    part leaves nothing to go over, so it is waived rather than reviewed.

    ``parts`` is how many parts the text has; it is read once, when the first part is said.
    The review never confirms: the confirming answer comes after, through ``respond``."""
    opened = _open(state, turn_id)
    if isinstance(opened, Err):
        return opened
    pending = opened.value
    if ready_to_confirm(pending):
        return Err("nothing_to_review")
    stage = pending.review
    if stage is not None and stage.turn_id == turn_id:
        return Err("same_turn")
    if stage is None and parts == 1:
        # One sentence has nothing to go over in parts: a yes says it again once, a carry-on
        # waives it; no offer in between.
        if answer == "affirm":
            return Ok(_say_part(pending, ReviewInParts(part=0, parts=1, turn_id=turn_id)))
        return Ok(pending.model_copy(update={"review": ReviewWaived(turn_id=turn_id)}))
    if isinstance(stage, ReviewOffered) and answer == "affirm":
        return Ok(_say_part(pending, ReviewInParts(part=0, parts=parts, turn_id=turn_id)))
    if isinstance(stage, ReviewInParts) and stage.part < stage.parts - 1 and answer == "affirm":
        moved = stage.model_copy(update={"part": stage.part + 1, "turn_id": turn_id})
        return Ok(_say_part(pending, moved))
    next_stage = ReviewOffered(turn_id=turn_id) if stage is None else ReviewWaived(turn_id=turn_id)
    return Ok(pending.model_copy(update={"review": next_stage}))


def start_parts(
    state: SessionState, turn_id: TurnId, *, parts: int
) -> Result[Confirmation, ConfirmationRefusal]:
    """Offer a cut read-back in parts once, without repeating its whole presentation."""
    opened = _open(state, turn_id)
    if isinstance(opened, Err):
        return opened
    pending = opened.value
    if pending.review is not None:
        return Err("already_reviewed")
    if pending.fully_delivered:
        return Err("nothing_to_review")
    return Ok(_say_part(pending, ReviewInParts(part=0, parts=parts, turn_id=turn_id)))


def assurance(confirmation: Confirmation) -> Assurance:
    """How a confirmed read-back was confirmed: heard whole, gone over to the end, or carried on
    without going over it. The export shows it."""
    if isinstance(confirmation.review, ReviewWaived):
        return "waived"
    return "heard" if confirmation.review is None else "reviewed"


def _open(state: SessionState, turn_id: TurnId) -> Result[Confirmation, ConfirmationRefusal]:
    """The pending confirmation, when the candidate's answer in ``turn_id`` may act on it."""
    pending = state.pending_confirmation
    if pending is None:
        return Err("nothing_pending")
    if pending.status != "pending":
        return Err("already_answered")
    if pending.presented_turn_id == turn_id:
        return Err("same_turn")
    return Ok(pending)


def _say_part(pending: Confirmation, stage: ReviewInParts) -> Confirmation:
    """Move to a part, unheard. The turn that says it is the one whose playback acknowledges it."""
    return pending.model_copy(
        update={"review": stage, "fully_delivered": False, "presented_turn_id": stage.turn_id}
    )


def invalidated_by_patch(
    state: SessionState,
    new_revision: int,
    changed: Sequence[CandidateFieldName] | None = None,
) -> Confirmation | None:
    """The pending confirmation after a fact changed: brief and slot targets referencing an
    older revision become ``invalidated``; a field target survives when ``changed`` names
    other fields than its own, and moves to ``new_revision`` so the candidate's yes can still
    confirm it. Answered confirmations are left as they are."""
    pending = state.pending_confirmation
    if pending is None or pending.status != "pending":
        return pending
    if isinstance(pending.target, FieldTarget):
        if changed is not None and pending.target.field not in changed:
            moved = pending.target.model_copy(update={"revision": new_revision})
            return pending.model_copy(update={"target": moved})
    elif _target_revision(pending.target) == new_revision:
        return pending
    return pending.model_copy(update={"status": "invalidated"})


def _target_revision(target: ConfirmationTarget) -> int:
    if isinstance(target, FieldTarget):
        return target.revision
    return target.revision if hasattr(target, "revision") else target.brief_revision
