"""The tool allowlist. One Pydantic model per tool; ``TOOL_SCHEMAS`` is generated from them.

The model sees exactly these nine names. Session, configuration, authorization and
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
    question: str = Field(min_length=1, max_length=500)


class ListInterviewSlotsArgs(Args):
    date_preference: date | None = None


class PresentConfirmationArgs(Args):
    target: Literal["field", "brief", "slot"]
    field: CandidateFieldName | None = None
    slot_id: SlotId | None = None


class ConfirmFieldArgs(Args):
    answer: Literal["affirm", "deny", "correct"]


class ConfirmBriefArgs(Args):
    answer: Literal["affirm", "deny", "correct"]


class ReserveInterviewArgs(Args):
    slot_id: SlotId


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
    "request_human_followup": RequestHumanFollowupArgs,
    "end_session": EndSessionArgs,
}

DESCRIPTIONS: dict[ToolName, str] = {
    "update_candidate": "Record facts the candidate just stated, or mark fields they declined "
    "or do not know. Never guess a value.",
    "search_knowledge": "Look up role, store, pay, shifts, training or policy facts before "
    "answering a question about them.",
    "list_interview_slots": "Get two or three available interview slots for this store.",
    "present_confirmation": "Read back a phone/date, the brief, or a proposed slot and wait "
    "for the candidate's answer.",
    "confirm_field": "Resolve the pending field read-back with the candidate's answer.",
    "confirm_brief": "Resolve the pending brief read-back with the candidate's answer.",
    "reserve_interview": "Reserve the slot the candidate just confirmed.",
    "request_human_followup": "Save a request for a person to follow up, with the reason.",
    "end_session": "Close the conversation for an allowed reason.",
}


def tool_schemas() -> tuple[ToolSchema, ...]:
    """JSON Schema for every allowlisted tool, generated once from the argument models."""
    return tuple(
        ToolSchema(name=name, description=DESCRIPTIONS[name], parameters=model.model_json_schema())
        for name, model in ARGUMENT_MODELS.items()
    )
