"""One session's journal and snapshot for the export tests: a phone read-back later
invalidated, a brief presented then confirmed, the session completed."""

import json
from datetime import datetime, timedelta

from cafe_norte.domain.contracts import (
    BriefTarget,
    CandidateRecord,
    ConfigId,
    Confirmation,
    ConfirmationId,
    FieldTarget,
    InputId,
    SessionId,
    SessionState,
    TurnId,
)
from cafe_norte.observability.contracts import UsageRecord
from cafe_norte.persistence.contracts import EventRecord, SessionSnapshot, TurnRecord
from cafe_norte.persistence.export import confirmations_from_events
from tests.support.builders import NOW, STAMP

SID = SessionId("s1")
PHONE = Confirmation(
    confirmation_id=ConfirmationId("c-phone"),
    target=FieldTarget(field="contact_phone", revision=1),
    presentation_text="Tu teléfono es 612 345 678, ¿es correcto?",
    presented_turn_id=TurnId("t1"),
)
BRIEF = Confirmation(
    confirmation_id=ConfirmationId("c-brief"),
    target=BriefTarget(revision=2),
    presentation_text="Te llamas Lucía Marín. ¿Es todo correcto?",
    presented_turn_id=TurnId("t2"),
    fully_delivered=True,
)


def state_updated(
    seq: int, *, pending: Confirmation | None, lifecycle: str = "active", at: datetime = NOW
) -> EventRecord:
    payload = {
        "type": "state_updated",
        "revision": 2,
        "pending_confirmation": None if pending is None else pending.model_dump(mode="json"),
        "lifecycle": lifecycle,
    }
    return EventRecord(
        session_id=SID,
        turn_id=TurnId(f"t{seq}"),
        seq=seq,
        kind="state_updated",
        payload_json=json.dumps(payload),
        at=at,
    )


def journal() -> tuple[EventRecord, ...]:
    """A phone read-back later invalidated, a brief presented then confirmed, the end."""
    confirmed = BRIEF.model_copy(update={"status": "confirmed", "response_turn_id": TurnId("t3")})
    return (
        EventRecord(
            session_id=SID,
            turn_id=TurnId("t1"),
            seq=1,
            kind="turn_started",
            payload_json="{}",
            at=NOW,
        ),
        state_updated(2, pending=PHONE),
        state_updated(3, pending=PHONE.model_copy(update={"status": "invalidated"})),
        state_updated(4, pending=BRIEF),
        state_updated(5, pending=confirmed),
        state_updated(6, pending=confirmed, lifecycle="completed", at=NOW + timedelta(minutes=3)),
    )


def snapshot(events: tuple[EventRecord, ...] = ()) -> SessionSnapshot:
    state = SessionState(
        session_id=SID,
        config_id=ConfigId("chamberi_barista_v1"),
        config_version="1",
        language="es",
        channel="text",
        created_at=NOW,
        lifecycle="completed",
        outcome="brief_only",
        candidate=CandidateRecord(revision=2),
        turn_count=4,
    )
    turn = TurnRecord(
        turn_id=TurnId("t1"),
        session_id=SID,
        input_id=InputId("i1"),
        role="user",
        channel="text",
        language="es",
        text="Me llamo Lucía Marín",
        started_at=NOW,
    )
    usage = UsageRecord(
        session_id=SID,
        turn_id=TurnId("t1"),
        kind="llm_tokens",
        quantity=120,
        unit_detail="input",
        estimated=False,
    )
    return SessionSnapshot(
        state=state,
        turns=(turn,),
        confirmations=confirmations_from_events(events),
        events=events,
        usage=(usage,),
        timings=(),
        versions=STAMP,
        taken_at=NOW,
    )
