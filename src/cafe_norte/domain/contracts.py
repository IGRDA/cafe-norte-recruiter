"""Domain types. Frozen Pydantic models and literal enums; no behaviour beyond validation.

Naming: ``*Id`` are opaque strings minted by the server. ``FieldState[T]`` is the sum type every
conversationally collected field uses. ``CandidatePatch`` is what the model may propose;
``CandidateRecord`` is what the server holds."""

from datetime import date, datetime
from typing import Annotated, Literal, NewType, TypeVar

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from cafe_norte.errors import Language

# ---- identifiers -------------------------------------------------------------------------------

SessionId = NewType("SessionId", str)
TurnId = NewType("TurnId", str)
InputId = NewType("InputId", str)  # chosen by the channel; duplicates are rejected
ConfirmationId = NewType("ConfirmationId", str)
SlotId = NewType("SlotId", str)
ConfigId = NewType("ConfigId", str)
ShiftId = NewType("ShiftId", str)


class Frozen(BaseModel):
    """Base for every domain record: immutable, strict about unknown keys."""

    model_config = ConfigDict(frozen=True, extra="forbid")


# ---- enums ---------------------------------------------------------------------------------------

Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
Interest = Literal["yes", "unsure", "no"]
WorkAuthorization = Literal["yes", "no", "unsure"]
Channel = Literal["voice", "text"]

Lifecycle = Literal["active", "paused", "completed", "stopped", "abandoned", "failed"]
Outcome = Literal[
    "reserved", "brief_only", "not_interested", "human_followup_requested", "incomplete"
]

# ---- value constraints ---------------------------------------------------------------------------

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
E164Phone = Annotated[str, StringConstraints(pattern=r"^\+[1-9]\d{6,14}$")]
HoursPerWeek = Annotated[int, Field(ge=1, le=60)]
Experience = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]

# ---- field algebra -------------------------------------------------------------------------------

T = TypeVar("T")


class Evidence(Frozen):
    """Where a value came from: finalized user text of one turn, never an STT interim."""

    source_turn_id: TurnId
    text: str


class Unset(Frozen):
    status: Literal["unset"] = "unset"


class Captured[T](Frozen):
    status: Literal["captured"] = "captured"
    value: T
    evidence: Evidence


class Confirmed[T](Frozen):
    status: Literal["confirmed"] = "confirmed"
    value: T
    evidence: Evidence
    confirmation_id: ConfirmationId


class Unknown(Frozen):
    """Two failed clarification attempts, or the candidate does not know."""

    status: Literal["unknown"] = "unknown"
    attempts: int = Field(ge=0)


class Declined(Frozen):
    status: Literal["declined"] = "declined"
    source_turn_id: TurnId


# PEP 695 alias: Pydantic collapses ``Captured[T]`` to ``Captured``, so a plain Union would not be
# subscriptable at runtime; ``type`` keeps the parameter so ``FieldState[str]`` works.
type FieldState[T] = Unset | Captured[T] | Confirmed[T] | Unknown | Declined


class CandidateRecord(Frozen):
    """Server-held candidate facts. The language is a session preference (``SessionState``),
    not a collected fact."""

    revision: int = Field(ge=0, default=0)
    name: Annotated[FieldState[Name], Field(discriminator="status")] = Unset()
    contact_phone: Annotated[FieldState[E164Phone], Field(discriminator="status")] = Unset()
    interest: Annotated[FieldState[Interest], Field(discriminator="status")] = Unset()
    work_authorization: Annotated[FieldState[WorkAuthorization], Field(discriminator="status")] = (
        Unset()
    )
    availability_days: Annotated[FieldState[frozenset[Weekday]], Field(discriminator="status")] = (
        Unset()
    )
    availability_shifts: Annotated[
        FieldState[frozenset[ShiftId]], Field(discriminator="status")
    ] = Unset()
    hours_per_week: Annotated[FieldState[HoursPerWeek], Field(discriminator="status")] = Unset()
    earliest_start_date: Annotated[FieldState[date], Field(discriminator="status")] = Unset()
    experience: Annotated[FieldState[Experience], Field(discriminator="status")] = Unset()
    notes: tuple[str, ...] = ()  # specific restrictions the candidate mentioned, verbatim


CandidateFieldName = Literal[
    "name",
    "contact_phone",
    "interest",
    "work_authorization",
    "availability_days",
    "availability_shifts",
    "hours_per_week",
    "earliest_start_date",
    "experience",
]

REQUESTED_FIELDS: tuple[CandidateFieldName, ...] = (
    "name",
    "interest",
    "work_authorization",
    "availability_days",
    "availability_shifts",
    "hours_per_week",
    "earliest_start_date",
    "experience",
)  # contact_phone is optional: never asked twice, never required for a booking


class CandidatePatch(Frozen):
    """What the model may propose in one ``update_candidate`` call. Every value is optional;
    ``None`` means "not mentioned". Relative dates are resolved by the runtime before this is
    built, so ``earliest_start_date`` is already a date. The server adds ``evidence``."""

    name: Name | None = None
    contact_phone: str | None = None  # raw; normalized to E.164 by domain validation
    interest: Interest | None = None
    work_authorization: WorkAuthorization | None = None
    availability_days: frozenset[Weekday] | None = None
    availability_shifts: frozenset[ShiftId] | None = None
    hours_per_week: HoursPerWeek | None = None
    earliest_start_date: date | None = None
    experience: Experience | None = None
    declined: frozenset[CandidateFieldName] = frozenset()
    unknown: frozenset[CandidateFieldName] = frozenset()
    note: Note | None = None


class FieldError(Frozen):
    """Why a value was refused. ``field`` is None for whole-patch problems."""

    field: CandidateFieldName | None
    reason: Literal[
        "invalid_format",
        "out_of_range",
        "past_date",
        "unknown_shift",
        "not_captured",
        "protected",
        "not_in_evidence",
    ]
    detail: str = ""


# ---- confirmations -------------------------------------------------------------------------------


class FieldTarget(Frozen):
    kind: Literal["field"] = "field"
    field: CandidateFieldName
    revision: int


class BriefTarget(Frozen):
    kind: Literal["brief"] = "brief"
    revision: int


class SlotTarget(Frozen):
    kind: Literal["slot"] = "slot"
    slot_id: SlotId
    brief_revision: int


ConfirmationTarget = Annotated[FieldTarget | BriefTarget | SlotTarget, Field(discriminator="kind")]

ConfirmationStatus = Literal["pending", "confirmed", "rejected", "invalidated", "expired"]


class ReviewOffered(Frozen):
    """The read-back was cut and Ana offered to go over it; the candidate has not chosen yet."""

    stage: Literal["offered"] = "offered"
    turn_id: TurnId  # the turn that made the move: one move per turn


class ReviewInParts(Frozen):
    """Being gone over in short parts; ``part`` is the one said last (0-based)."""

    stage: Literal["in_parts"] = "in_parts"
    part: int
    parts: int
    turn_id: TurnId


class ReviewWaived(Frozen):
    """The candidate chose to carry on without going over it: an informed skip."""

    stage: Literal["waived"] = "waived"
    turn_id: TurnId


Review = Annotated[ReviewOffered | ReviewInParts | ReviewWaived, Field(discriminator="stage")]


class Confirmation(Frozen):
    """One read-back and its answer. A bare "yes" only means something against the pending one."""

    confirmation_id: ConfirmationId
    target: ConfirmationTarget
    presentation_text: str  # canonical recap, the exact words shown or spoken
    presented_turn_id: TurnId
    fully_delivered: bool = False  # the latest saying (whole text or one part) was heard to its end
    review: Review | None = None  # None: said once, whole; set after a cut (D39)
    response_turn_id: TurnId | None = None
    status: ConfirmationStatus = "pending"
    source: Literal["model", "ui"] = "model"


# ---- calendar and booking ------------------------------------------------------------------------


class InterviewSlot(Frozen):
    slot_id: SlotId
    config_id: ConfigId
    starts_at_utc: datetime
    duration_minutes: int = 30
    status: Literal["available", "reserved"] = "available"


class OfferedSlot(Frozen):
    slot_id: SlotId
    starts_at_utc: datetime


class SlotOffer(Frozen):
    """The slots Ana last offered, in the order she said them, and the ones an ambiguous answer
    left in question (D41). The runtime matches the candidate's choice against it."""

    slots: tuple[OfferedSlot, ...]
    shortlist: tuple[SlotId, ...] = ()


class Booking(Frozen):
    """A committed simulated reservation. Exists only after the database transaction commits."""

    slot_id: SlotId
    config_id: ConfigId
    starts_at_utc: datetime
    confirmation_id: ConfirmationId
    idempotency_key: str
    committed_at: datetime
    simulated: Literal[True] = True


BookingRefusal = Literal[
    "session_not_active",
    "brief_not_confirmed",
    "no_schedule_intent",
    "confirmation_missing",
    "confirmation_not_delivered",
    "confirmation_mismatch",
    "slot_in_past",
    "slot_unavailable",
    "slot_other_store",
    "already_booked",
]

# ---- review and signals --------------------------------------------------------------------------


class ReviewFlag(Frozen):
    kind: Literal[
        "work_authorization",
        "human_followup",
        "unsupported_question",
        "reschedule_request",
        "other",
    ]
    turn_id: TurnId
    note: str


Sentiment = Literal["neutral", "positive", "frustrated", "uncertain"]


class Signal(Frozen):
    """Conversational signal attached to the turn it came from; never a hiring input."""

    turn_id: TurnId
    sentiment: Sentiment
    explicit_human_request: bool
    explicit_stop: bool
    language_switch_to: Language | None
    evidence_text: str


# ---- configuration -------------------------------------------------------------------------------


class ShiftDefinition(Frozen):
    shift_id: ShiftId
    label: dict[Language, str]
    starts: str  # "HH:MM" local
    ends: str
    days: frozenset[Weekday]


class StoreConfiguration(Frozen):
    """One of the two versioned configurations. Fixed for the life of a session."""

    config_id: ConfigId
    version: str
    store_name: str
    city: str
    address: str  # fictional
    timezone: Literal["Europe/Madrid"] = "Europe/Madrid"
    hours_per_week: int
    shifts: tuple[ShiftDefinition, ...]
    interview_times: tuple[str, ...]  # "HH:MM" local; one 30-minute slot each, on shift days
    kb_version: str
    kb_doc_ids: frozenset[str]


# ---- session -------------------------------------------------------------------------------------


class SessionState(Frozen):
    """The authoritative state the runtime reads and the repositories persist."""

    session_id: SessionId
    config_id: ConfigId
    config_version: str
    language: Language
    channel: Channel
    created_at: datetime
    lifecycle: Lifecycle = "active"
    outcome: Outcome | None = None
    candidate: CandidateRecord = CandidateRecord()
    pending_confirmation: Confirmation | None = None
    brief_confirmed_revision: int | None = None  # the revision the candidate last confirmed
    schedule_intent: Evidence | None = None  # the candidate's words asking for an interview
    slot_offer: SlotOffer | None = None  # the slots last offered, for the runtime's matcher
    booking: Booking | None = None
    review_flags: tuple[ReviewFlag, ...] = ()
    active_seconds: float = 0.0
    turn_count: int = 0
