"""Going over a read-back the candidate cut: its short parts, and which tool a plain
answer calls.

A part is a slice of the read-back's own sentences, so what is gone over is the text that is
confirmed; each part ends with the short check from ``prompts/brief.<language>.md``."""

from typing import Literal

from cafe_norte.conversation.brief import brief_intro, review_check
from cafe_norte.conversation.prompt import sentences
from cafe_norte.conversation.signals import ReadbackAnswer
from cafe_norte.conversation.tools import ToolName
from cafe_norte.domain.confirmation import ready_to_confirm
from cafe_norte.domain.contracts import (
    Confirmation,
    ConfirmationTarget,
    ReviewInParts,
    ReviewOffered,
    SlotTarget,
    TurnId,
)
from cafe_norte.errors import Language

RuntimeCall = tuple[ToolName, dict[str, str]]  # a tool and its arguments, as the model sends them
CONFIRM_TOOL: dict[Literal["field", "brief", "slot"], ToolName] = {
    "field": "confirm_field",
    "brief": "confirm_brief",
    "slot": "reserve_interview",
}

PART_SENTENCES = 2  # sentences of the read-back per part
PART_CHARACTERS = 160  # a part of two sentences stays under this (one longer sentence is alone)


def review_parts(presentation_text: str, language: Language) -> tuple[str, ...]:
    """The read-back without its intro and closing question, in parts short enough to hear to
    the end, each followed by the check. A one-sentence read-back is one part."""
    said = sentences(presentation_text)
    if said and said[-1].endswith("?"):
        said = said[:-1]
    if said and said[0] == brief_intro(language):
        said = said[1:]
    groups: list[list[str]] = []
    for sentence in said:
        fits = groups and len(groups[-1]) < PART_SENTENCES
        if fits and len(" ".join([*groups[-1], sentence])) <= PART_CHARACTERS:
            groups[-1].append(sentence)
        else:
            groups.append([sentence])
    check = review_check(language)
    return tuple(" ".join([*group, check]) for group in groups) or (presentation_text,)


def current_saying(pending: Confirmation, language: Language) -> str:
    """What was said last of the read-back: the part under review, or the whole text."""
    stage = pending.review
    if isinstance(stage, ReviewInParts):
        return review_parts(pending.presentation_text, language)[stage.part]
    return pending.presentation_text


def target_call(target: ConfirmationTarget, answer: Literal["affirm", "deny"]) -> RuntimeCall:
    """The read-back's own tool with the candidate's answer; a slot's yes is its reservation."""
    if isinstance(target, SlotTarget):
        return CONFIRM_TOOL["slot"], {"slot_id": str(target.slot_id)}
    return CONFIRM_TOOL[target.kind], {"answer": answer}


def answer_call(
    pending: Confirmation | None, answer: ReadbackAnswer, turn_id: TurnId
) -> RuntimeCall | None:
    """The tool a plain answer in ``turn_id`` calls, by where the read-back stands; ``None``
    leaves the answer to the model.

    | read-back | yes | carry on | no |
    | ready to confirm | its tool, yes | its tool, yes | its tool, no |
    | cut, not reviewed | review, yes (the offer) | review, carry on (the offer) | its tool, no |
    | offered | review, yes (first part) | review, carry on | review, carry on |
    | in parts | review, yes (next part) | review, carry on | its tool, no |

    A no to a slot is about another slot or none: the model's. A no to the offer ("shall we go
    over it?") is carrying on. Nothing is routed in the turn that said the read-back or moved
    its review: the candidate has not answered that yet."""
    if pending is None or pending.status != "pending" or pending.presented_turn_id == turn_id:
        return None
    stage = pending.review
    if stage is not None and stage.turn_id == turn_id:
        return None
    if answer == "deny" and isinstance(stage, ReviewOffered):
        answer = "skip"
    if answer == "deny":
        return (
            None if isinstance(pending.target, SlotTarget) else target_call(pending.target, "deny")
        )
    if ready_to_confirm(pending):
        return target_call(pending.target, "affirm")
    return "review_readback", {"answer": answer}
