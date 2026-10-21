"""Going over a read-back the candidate cut (D39): its short parts.

A part is a slice of the read-back's own sentences, so what is gone over is the text that is
confirmed (D20); each part ends with the short check from ``prompts/brief.<language>.md``."""

from typing import Literal

from cafe_norte.conversation.brief import brief_intro, review_check
from cafe_norte.conversation.prompt import sentences
from cafe_norte.conversation.tools import ToolName
from cafe_norte.domain.contracts import Confirmation, ConfirmationTarget, ReviewInParts, SlotTarget
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
