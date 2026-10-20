"""The JSON export: ``ExportDocument`` is the schema the spec asks to publish."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from cafe_norte.domain.contracts import (
    Booking,
    CandidateRecord,
    Confirmation,
    Lifecycle,
    Outcome,
    ReviewFlag,
    SessionId,
    Signal,
)
from cafe_norte.observability.contracts import StageTiming, UsageRecord, VersionStamp
from cafe_norte.persistence.contracts import EventRecord, SessionSnapshot, TurnRecord

SCHEMA_VERSION: Literal["1"] = "1"


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SessionExport(Frozen):
    session_id: SessionId
    config_id: str
    config_version: str
    language: str
    channel: str
    lifecycle: Lifecycle
    outcome: Outcome | None
    created_at: datetime
    ended_at: datetime | None
    active_seconds: float
    simulated_reservation_notice: Literal["Simulated reservation — no real appointment created"]


class RetrievalEvent(Frozen):
    turn_id: str
    question: str
    sources: tuple[str, ...]  # chunk ids
    answered: bool


class Summary(Frozen):
    brief: str  # deterministic rendering of the accepted record
    narrative: str | None  # model-written, optional, never the source of truth
    narrative_status: Literal["pending", "done", "failed", "skipped"]


class Metrics(Frozen):
    turns: int
    timings: tuple[StageTiming, ...]
    usage: tuple[UsageRecord, ...]
    estimated_marginal_cost_eur: float | None
    cost_is_partial: bool


class ExportDocument(Frozen):
    """Never contains access codes, credentials, resume tokens or audio."""

    schema_version: Literal["1"] = SCHEMA_VERSION
    session: SessionExport
    candidate: CandidateRecord
    transcript: tuple[TurnRecord, ...]
    confirmations: tuple[Confirmation, ...]
    booking: Booking | None
    review_flags: tuple[ReviewFlag, ...]
    retrieval_events: tuple[RetrievalEvent, ...]
    signals: tuple[Signal, ...]
    events: tuple[EventRecord, ...]
    summary: Summary
    metrics: Metrics
    versions: VersionStamp


def build_export(snapshot: SessionSnapshot) -> ExportDocument:
    """Pure: one consistent snapshot in, one document out."""
    raise NotImplementedError
