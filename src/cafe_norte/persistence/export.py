"""The JSON export: ``ExportDocument`` is the schema the spec asks to publish, and
``build_export`` fills it from one ``SessionSnapshot``."""

import json
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from cafe_norte.domain.contracts import (
    Booking,
    BriefTarget,
    CandidateRecord,
    Confirmation,
    Lifecycle,
    Outcome,
    ReviewFlag,
    SessionId,
    Signal,
)
from cafe_norte.domain.lifecycle import TERMINAL
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


RESERVATION_NOTICE: Literal["Simulated reservation — no real appointment created"] = (
    "Simulated reservation — no real appointment created"
)


def build_export(snapshot: SessionSnapshot) -> ExportDocument:
    """Pure: one consistent snapshot in, one document out. The brief is the text the
    candidate actually heard and confirmed; cost stays ``None`` until prices are recorded."""
    state = snapshot.state
    return ExportDocument(
        session=SessionExport(
            session_id=state.session_id,
            config_id=state.config_id,
            config_version=state.config_version,
            language=state.language,
            channel=state.channel,
            lifecycle=state.lifecycle,
            outcome=state.outcome,
            created_at=state.created_at,
            ended_at=ended_at(snapshot.events),
            active_seconds=state.active_seconds,
            simulated_reservation_notice=RESERVATION_NOTICE,
        ),
        candidate=state.candidate,
        transcript=snapshot.turns,
        confirmations=snapshot.confirmations,
        booking=state.booking,
        review_flags=state.review_flags,
        retrieval_events=(),
        signals=(),
        events=snapshot.events,
        summary=Summary(
            brief=brief_text(snapshot.confirmations), narrative=None, narrative_status="skipped"
        ),
        metrics=Metrics(
            turns=sum(1 for t in snapshot.turns if t.role == "user"),  # the candidate's turns
            timings=snapshot.timings,
            usage=snapshot.usage,
            estimated_marginal_cost_eur=None,
            cost_is_partial=True,
        ),
        versions=snapshot.versions,
    )


def confirmations_from_events(events: tuple[EventRecord, ...]) -> tuple[Confirmation, ...]:
    """The confirmation history: every ``state_updated`` event carries the pending
    confirmation as it was committed, so the last record per id is its final status. Order
    is first appearance."""
    history: dict[str, Confirmation] = {}
    for event in events:
        if event.kind != "state_updated":
            continue
        pending = json.loads(event.payload_json).get("pending_confirmation")
        if pending is None:
            continue
        confirmation = Confirmation.model_validate(pending)
        history[confirmation.confirmation_id] = confirmation
    return tuple(history.values())


def ended_at(events: tuple[EventRecord, ...]) -> datetime | None:
    """When the session's lifecycle became terminal: the commit time of that state."""
    for event in events:
        if event.kind != "state_updated":
            continue
        if json.loads(event.payload_json).get("lifecycle") in TERMINAL:
            return event.at
    return None


def brief_text(confirmations: tuple[Confirmation, ...]) -> str:
    """The deterministic brief: the last confirmed brief read-back, else the last presented
    one, else nothing."""
    briefs = [c for c in confirmations if isinstance(c.target, BriefTarget)]
    confirmed = [c for c in briefs if c.status == "confirmed"]
    chosen = (confirmed or briefs)[-1:]
    return chosen[0].presentation_text if chosen else ""
