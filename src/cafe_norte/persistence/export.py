"""``ExportDocument`` defines the public session export schema.

``build_export`` fills it from one ``SessionSnapshot``.
"""

import json
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict

from cafe_norte.domain.confirmation import Assurance, assurance
from cafe_norte.domain.contracts import (
    Booking,
    BriefTarget,
    CandidateRecord,
    ConfigId,
    Confirmation,
    Lifecycle,
    Outcome,
    ReviewFlag,
    SessionId,
    Signal,
)
from cafe_norte.domain.lifecycle import TERMINAL
from cafe_norte.observability.contracts import (
    Estimator,
    StageTiming,
    UsageKind,
    UsageRecord,
    VersionStamp,
)
from cafe_norte.persistence.contracts import EventRecord, SessionSnapshot, TurnRecord

if TYPE_CHECKING:
    from cafe_norte.persistence.contracts import Store

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
    """One ``search_knowledge`` call: what was asked and which chunks were shown. Whether
    the answer was right is a judgement for the evaluation, not a field."""

    turn_id: str
    question: str
    sources: tuple[str, ...]  # chunk ids
    sources_found: bool


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


class ExportedConfirmation(Confirmation):
    """A read-back as the export shows it: with how a confirmed one was confirmed, heard
    whole, gone over to the end, or carried on without going over it. ``None`` otherwise."""

    assurance: Assurance | None = None

    @classmethod
    def of(cls, confirmation: Confirmation) -> "ExportedConfirmation":
        confirmed = confirmation.status == "confirmed"
        return cls(**dict(confirmation), assurance=assurance(confirmation) if confirmed else None)


class ExportDocument(Frozen):
    """Never contains access codes, credentials, resume tokens or audio."""

    schema_version: Literal["1"] = SCHEMA_VERSION
    session: SessionExport
    candidate: CandidateRecord
    transcript: tuple[TurnRecord, ...]
    confirmations: tuple[ExportedConfirmation, ...]
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


async def persist_export(
    store: "Store",
    session_id: SessionId,
    *,
    versions_for: Callable[[ConfigId], VersionStamp],
    now: datetime,
    estimate: Estimator | None = None,
) -> None:
    """Build the session's export from one snapshot and store it: what a closed session serves
    from then on. Idempotent; a second close overwrites."""
    state = await store.sessions.get(session_id)
    if state is None:
        return
    snapshot = await store.snapshot(
        session_id, versions=versions_for(state.config_id), taken_at=now
    )
    if snapshot is None:
        return
    document = build_export(snapshot, estimate=estimate)
    async with store.transaction() as tx:
        await store.exports.write_snapshot(tx, session_id, document.model_dump_json(indent=2))


def build_export(snapshot: SessionSnapshot, *, estimate: Estimator | None = None) -> ExportDocument:
    """Pure: one consistent snapshot in, one document out. The brief is the text the
    candidate actually heard and confirmed. Without an ``estimate`` the cost is unknown."""
    state = snapshot.state
    derived = voice_usage(snapshot)
    usage = (*snapshot.usage, *derived)
    cost = None if estimate is None else estimate(state.session_id, usage)
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
        confirmations=tuple(ExportedConfirmation.of(c) for c in snapshot.confirmations),
        booking=state.booking,
        review_flags=state.review_flags,
        retrieval_events=retrieval_events_from_events(snapshot.events),
        signals=signals_from_events(snapshot.events),
        events=snapshot.events,
        summary=Summary(
            brief=brief_text(snapshot.confirmations), narrative=None, narrative_status="skipped"
        ),
        metrics=Metrics(
            turns=sum(1 for t in snapshot.turns if t.role == "user"),  # the candidate's turns
            timings=snapshot.timings,
            usage=usage,
            estimated_marginal_cost_eur=None if cost is None else cost.marginal_eur,
            # Partial when something is missing: no prices, or speech nothing measured.
            # An estimate of a cut generation is flagged on its record, not here.
            cost_is_partial=cost is None or bool(cost.missing_prices) or bool(derived),
        ),
        versions=snapshot.versions,
    )


def voice_usage(snapshot: SessionSnapshot) -> tuple[UsageRecord, ...]:
    """What a voice session used that nothing measured, derived from the snapshot: the
    characters Ana spoke, the seconds the candidate was heard, and the minutes of the bot and
    the candidate in the room. A kind the call measured is never derived again."""
    state = snapshot.state
    if state.channel != "voice":
        return ()
    measured = {record.kind for record in snapshot.usage if not record.estimated}
    spoken = sum(len(turn.text) for turn in snapshot.turns if turn.role == "assistant")
    derived: tuple[tuple[UsageKind, str, float], ...] = (
        ("tts_characters", snapshot.versions.tts_model, float(spoken)),
        ("stt_seconds", snapshot.versions.stt_model, state.active_seconds),
        ("media_participant_minutes", "daily", 2 * state.active_seconds / 60),
    )
    return tuple(
        UsageRecord(
            session_id=state.session_id,
            turn_id=None,
            kind=kind,
            quantity=quantity,
            unit_detail=detail,
            estimated=True,
        )
        for kind, detail, quantity in derived
        if kind not in measured
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


def retrieval_events_from_events(events: tuple[EventRecord, ...]) -> tuple[RetrievalEvent, ...]:
    """Every journaled ``sources_shown`` event, in order."""
    found: list[RetrievalEvent] = []
    for event in events:
        if event.kind != "sources_shown":
            continue
        payload = json.loads(event.payload_json)
        sources = tuple(payload.get("chunk_ids", ()))
        found.append(
            RetrievalEvent(
                turn_id=event.turn_id or "",
                question=payload.get("question", ""),
                sources=sources,
                sources_found=bool(sources),
            )
        )
    return tuple(found)


def signals_from_events(events: tuple[EventRecord, ...]) -> tuple[Signal, ...]:
    """Every journaled ``signal_recorded`` verdict, in order of arrival."""
    return tuple(
        Signal.model_validate(json.loads(event.payload_json)["signal"])
        for event in events
        if event.kind == "signal_recorded"
    )


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
