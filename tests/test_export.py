"""The export document: one snapshot in, one document out; the confirmation history and the
session's end come from the journaled ``state_updated`` events."""

import json
from datetime import UTC, datetime, timedelta

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
from cafe_norte.observability.contracts import UsageRecord, VersionStamp
from cafe_norte.persistence.contracts import EventRecord, SessionSnapshot, TurnRecord
from cafe_norte.persistence.export import (
    SCHEMA_VERSION,
    ExportDocument,
    brief_text,
    build_export,
    confirmations_from_events,
    ended_at,
)
from cafe_norte.persistence.memory import MemoryStore

NOW = datetime(2026, 10, 20, 10, tzinfo=UTC)
SID = SessionId("s1")
VERSIONS = VersionStamp(
    config_id=ConfigId("chamberi_barista_v1"),
    config_version="1",
    kb_version="1",
    prompt_version="ana_v4",
    schema_version=SCHEMA_VERSION,
    model_id="fake",
    commit_sha="local",
)
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
        versions=VERSIONS,
        taken_at=NOW,
    )


def test_confirmation_history_keeps_the_final_status_per_id_in_order_of_appearance() -> None:
    history = confirmations_from_events(journal())
    assert [c.confirmation_id for c in history] == ["c-phone", "c-brief"]
    assert [c.status for c in history] == ["invalidated", "confirmed"]
    assert history[1].response_turn_id == "t3"


def test_the_session_ends_when_its_lifecycle_becomes_terminal() -> None:
    assert ended_at(journal()) == NOW + timedelta(minutes=3)
    assert ended_at(journal()[:5]) is None


def test_the_brief_is_the_confirmed_read_back_else_the_last_presented_else_nothing() -> None:
    assert brief_text(confirmations_from_events(journal())) == BRIEF.presentation_text
    assert brief_text((PHONE, BRIEF)) == BRIEF.presentation_text
    assert brief_text((PHONE,)) == ""


def test_build_export_fills_every_section_from_the_snapshot() -> None:
    document = build_export(snapshot(journal()))
    assert document.schema_version == "1"
    assert document.session.created_at == NOW
    assert document.session.ended_at == NOW + timedelta(minutes=3)
    assert (document.session.lifecycle, document.session.outcome) == ("completed", "brief_only")
    assert document.summary.brief == BRIEF.presentation_text
    assert document.summary.narrative_status == "skipped"
    assert document.metrics.turns == 1 and document.metrics.cost_is_partial
    assert document.metrics.estimated_marginal_cost_eur is None
    assert len(document.transcript) == 1 and len(document.confirmations) == 2
    assert document.versions == VERSIONS
    again = ExportDocument.model_validate_json(document.model_dump_json())
    assert again == document


def test_the_schema_never_names_a_secret() -> None:
    schema = ExportDocument.model_json_schema()
    names: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            names.update(node.get("properties", {}))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(schema)
    assert not {n for n in names if "hash" in n or "token" in n or "secret" in n}


async def test_memory_store_snapshot_reads_the_whole_session() -> None:
    store = MemoryStore()
    base = snapshot()
    await store.sessions.create(base.state, access_hash="secret")
    async with store.transaction() as tx:
        await store.turns.append(tx, base.turns[0])
        for event in journal():
            await store.events.append(tx, event)
        await store.events.record_usage(tx, base.usage[0])
        await store.events.record_usage(tx, base.usage[0].model_copy(update={"session_id": "x"}))
    taken = await store.snapshot(SID, versions=VERSIONS, taken_at=NOW)
    assert taken is not None
    assert taken.turns == base.turns and len(taken.events) == 6
    assert [c.status for c in taken.confirmations] == ["invalidated", "confirmed"]
    assert taken.usage == base.usage and taken.timings == ()
    assert "secret" not in build_export(taken).model_dump_json()
    assert await store.snapshot(SessionId("nope"), versions=VERSIONS, taken_at=NOW) is None
