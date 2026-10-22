"""The tool allowlist. One Pydantic model per tool; ``TOOL_SCHEMAS`` is generated from them.

The model sees exactly these ten names. Session, configuration, authorization and
idempotency are never arguments."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from cafe_norte.domain.contracts import CandidateFieldName, CandidatePatch, SlotId
from cafe_norte.errors import Language
from cafe_norte.model.contracts import ToolSchema

ToolName = Literal[
    "update_candidate",
    "search_knowledge",
    "list_interview_slots",
    "present_confirmation",
    "confirm_field",
    "confirm_brief",
    "reserve_interview",
    "review_readback",
    "request_human_followup",
    "end_session",
]


class Args(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class UpdateCandidateArgs(Args):
    """The patch plus the exact words it came from. The server resolves the source turn."""

    patch: CandidatePatch
    evidence_text: str = Field(min_length=1, max_length=1000)


class SearchKnowledgeArgs(Args):
    """The candidate's words for the record and the model's self-contained Spanish queries
    for the index (English questions are reformulated here). No topic: a model-chosen topic
    hid answers its documents did not include (D54)."""

    question: str = Field(min_length=1, max_length=500)
    queries: tuple[str, ...] = Field(min_length=1, max_length=3)


class ListInterviewSlotsArgs(Args):
    """The candidate's words asking for an interview are the explicit intent to schedule."""

    evidence_text: str = Field(min_length=1, max_length=500)
    date_preference: date | None = None


class PresentConfirmationArgs(Args):
    """A slot is named by its number in ``interview_slots`` (``choice``); an id is still
    accepted. ``evidence_text`` is the candidate's words asking for the interview, needed while
    the session has none (D56)."""

    target: Literal["field", "brief", "slot"]
    field: CandidateFieldName | None = None
    choice: int | None = Field(default=None, ge=1, le=9)
    slot_id: SlotId | None = None
    evidence_text: str | None = Field(default=None, min_length=1, max_length=500)


class ConfirmFieldArgs(Args):
    answer: Literal["affirm", "deny", "correct"]


class ConfirmBriefArgs(Args):
    answer: Literal["affirm", "deny", "correct"]


class ReserveInterviewArgs(Args):
    slot_id: SlotId


class ReviewReadbackArgs(Args):
    """The candidate's answer to a read-back they did not hear to the end (D39)."""

    answer: Literal["affirm", "skip"]


class RequestHumanFollowupArgs(Args):
    reason: str = Field(min_length=1, max_length=500)


class EndSessionArgs(Args):
    reason: Literal["candidate_done", "not_interested", "candidate_stop", "limit"]
    language: Language | None = None


ARGUMENT_MODELS: dict[ToolName, type[Args]] = {
    "update_candidate": UpdateCandidateArgs,
    "search_knowledge": SearchKnowledgeArgs,
    "list_interview_slots": ListInterviewSlotsArgs,
    "present_confirmation": PresentConfirmationArgs,
    "confirm_field": ConfirmFieldArgs,
    "confirm_brief": ConfirmBriefArgs,
    "reserve_interview": ReserveInterviewArgs,
    "review_readback": ReviewReadbackArgs,
    "request_human_followup": RequestHumanFollowupArgs,
    "end_session": EndSessionArgs,
}

DESCRIPTIONS: dict[ToolName, str] = {
    "update_candidate": "Record facts the candidate just stated, or mark fields they declined "
    "or do not know. Patch values are plain strings, numbers, dates or lists, never objects. "
    "Never guess a value.",
    "search_knowledge": "Look up facts about the role, the store, pay, shifts, training, "
    "uniform, benefits, the interview or the company. Call it for every such question, in "
    "the same turn, even if you think you know the answer; never state these facts without it. "
    "`question` is what the candidate said; `queries` are one to three self-contained Spanish "
    "phrasings of it with the key words (two when the question is vague or in English); "
    "The store's documents are searched; nothing else narrows them.",
    "list_interview_slots": "Look for other interview times, for the day the candidate asks "
    "(date_preference), with their exact words in evidence_text. The times you may offer are "
    "already in interview_slots; offer them in your own words.",
    "present_confirmation": "Read back a phone/date, the brief, or the slot the candidate chose "
    "(target=slot with its number in interview_slots as choice, and their words asking for the "
    "interview in evidence_text) and wait for the candidate's answer.",
    "confirm_field": "Resolve the pending field read-back with the candidate's answer.",
    "confirm_brief": "Resolve the pending brief read-back with the candidate's answer.",
    "reserve_interview": "The candidate said yes to the slot read-back: reserve that slot_id. "
    "Call it only after they answered.",
    "review_readback": "The candidate answered a read-back they did not hear to the end "
    "(pending_confirmation.heard is false): affirm when they want to go over it or say yes to "
    "a part, skip when they want to carry on without going over it. The system speaks the "
    "parts and confirms a skip for you.",
    "request_human_followup": "Save a request for a person to follow up, with the reason: "
    "the candidate's unanswered question, their wish to talk to a person, or what they want "
    "the team to look at (a complaint, a claim about their conditions). Call it once the "
    "candidate accepts the offer; a note is never read by a person. Nobody real is notified "
    "in this demo.",
    "end_session": "Close the conversation for an allowed reason.",
}


def tool_schemas() -> tuple[ToolSchema, ...]:
    """JSON Schema for every allowlisted tool, generated once from the argument models."""
    return tuple(
        ToolSchema(name=name, description=DESCRIPTIONS[name], parameters=model.model_json_schema())
        for name, model in ARGUMENT_MODELS.items()
    )
