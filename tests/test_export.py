"""The export document: one snapshot in, one document out; the confirmation history and the
session's end come from the journaled ``state_updated`` events."""

import json
from datetime import UTC, datetime, timedelta
from functools import partial

import pytest

from cafe_norte.domain.contracts import (
    BriefTarget,
    CandidateRecord,
    ConfigId,
    Confirmation,
    ConfirmationId,
    FieldTarget,
    InputId,
    ReviewWaived,
    SessionId,
    SessionState,
    TurnId,
)
from cafe_norte.observability.contracts import (
    Price,
    PriceTable,
    UsageKind,
    UsageRecord,
    VersionStamp,
)
from cafe_norte.observability.cost import estimate
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


def test_each_confirmed_read_back_says_whether_it_was_heard_reviewed_or_waived() -> None:
    """D39: a carry-on confirms a read-back the candidate did not hear to the end; the export
    keeps it apart from one heard whole or gone over to the end."""
    waived = BRIEF.model_copy(
        update={
            "fully_delivered": False,
            "review": ReviewWaived(turn_id=TurnId("t3")),
            "status": "confirmed",
            "response_turn_id": TurnId("t3"),
        }
    )
    events = (*journal()[:4], state_updated(5, pending=waived))
    document = build_export(snapshot(events))
    assert [(c.status, c.assurance) for c in document.confirmations] == [
        ("invalidated", None),
        ("confirmed", "waived"),
    ]
    heard = build_export(snapshot(journal()))
    assert [c.assurance for c in heard.confirmations] == [None, "heard"]


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


def test_retrieval_events_come_from_journaled_sources() -> None:
    from cafe_norte.persistence.export import retrieval_events_from_events

    shown = EventRecord(
        session_id=SID,
        turn_id=TurnId("t5"),
        seq=7,
        kind="sources_shown",
        payload_json=json.dumps({"question": "¿horas?", "chunk_ids": ["offer_chamberi#horas"]}),
        at=NOW,
    )
    none = shown.model_copy(
        update={"seq": 8, "payload_json": json.dumps({"question": "¿parking?", "chunk_ids": []})}
    )
    events = retrieval_events_from_events((*journal(), shown, none))
    assert [(e.turn_id, e.sources_found) for e in events] == [("t5", True), ("t5", False)]
    assert events[0].sources == ("offer_chamberi#horas",) and events[1].question == "¿parking?"
    assert build_export(snapshot((*journal(), shown))).retrieval_events == events[:1]


def test_signals_come_from_journaled_verdicts() -> None:
    from cafe_norte.conversation.contracts import SignalRecorded
    from cafe_norte.domain.contracts import Signal
    from cafe_norte.persistence.export import signals_from_events

    verdict = Signal(
        turn_id=TurnId("t2"),
        sentiment="frustrated",
        explicit_human_request=False,
        explicit_stop=False,
        language_switch_to=None,
        evidence_text="muy lento",
    )
    recorded = EventRecord(
        session_id=SID,
        turn_id=TurnId("t2"),
        seq=9,
        kind="signal_recorded",
        payload_json=SignalRecorded(signal=verdict).model_dump_json(),
        at=NOW,
    )
    assert signals_from_events((*journal(), recorded)) == (verdict,)
    assert build_export(snapshot((*journal(), recorded))).signals == (verdict,)


PRICES = PriceTable(
    version="test-1",
    verified_on=NOW,
    prices=(
        Price(kind="llm_tokens", unit_detail="m:input", eur_per_unit=0.000001),
        Price(kind="llm_tokens", unit_detail="m:output", eur_per_unit=0.000004),
        Price(kind="stt_seconds", unit_detail="nova-3", eur_per_unit=0.001),
        Price(kind="tts_characters", unit_detail="eleven_flash_v2_5", eur_per_unit=0.0001),
        Price(kind="media_participant_minutes", unit_detail="daily", eur_per_unit=0.01),
    ),
)
PRICED = partial(estimate, prices=PRICES)


def with_usage(base: SessionSnapshot, *details: tuple[str, float]) -> SessionSnapshot:
    records = tuple(
        UsageRecord(
            session_id=SID,
            turn_id=TurnId("t1"),
            kind="llm_tokens",
            quantity=quantity,
            unit_detail=detail,
            estimated=False,
        )
        for detail, quantity in details
    )
    return base.model_copy(update={"usage": records})


def test_a_priced_text_session_has_a_complete_cost() -> None:
    taken = with_usage(snapshot(), ("m:input", 1000), ("m:output", 500))
    metrics = build_export(taken, estimate=PRICED).metrics
    assert metrics.estimated_marginal_cost_eur == pytest.approx(0.003)
    assert metrics.cost_is_partial is False


def test_an_unpriced_model_makes_the_cost_partial() -> None:
    taken = with_usage(snapshot(), ("m:input", 1000), ("unknown:output", 500))
    metrics = build_export(taken, estimate=PRICED).metrics
    assert metrics.estimated_marginal_cost_eur == pytest.approx(0.001)
    assert metrics.cost_is_partial is True


def test_without_an_estimator_the_cost_is_unknown() -> None:
    metrics = build_export(with_usage(snapshot(), ("m:input", 1000))).metrics
    assert metrics.estimated_marginal_cost_eur is None
    assert metrics.cost_is_partial is True


def voice_snapshot() -> SessionSnapshot:
    base = snapshot()
    spoken = base.turns[0].model_copy(
        update={"turn_id": TurnId("t2"), "role": "assistant", "text": "Hola, soy Ana"}
    )
    return base.model_copy(
        update={
            "state": base.state.model_copy(update={"channel": "voice", "active_seconds": 120.0}),
            "turns": (*base.turns, spoken),
            "versions": base.versions.model_copy(
                update={"stt_model": "nova-3", "tts_model": "eleven_flash_v2_5"}
            ),
        }
    )


def test_a_voice_session_derives_its_voice_usage_as_estimated() -> None:
    document = build_export(with_usage(voice_snapshot(), ("m:input", 1000)), estimate=PRICED)
    derived = {(r.kind, r.unit_detail): r.quantity for r in document.metrics.usage if r.estimated}
    assert derived == {
        ("tts_characters", "eleven_flash_v2_5"): len("Hola, soy Ana"),
        ("stt_seconds", "nova-3"): 120.0,
        ("media_participant_minutes", "daily"): 4.0,  # the bot and the candidate, 2 minutes
    }
    expected = 1000 * 0.000001 + 13 * 0.0001 + 120 * 0.001 + 4 * 0.01
    assert document.metrics.estimated_marginal_cost_eur == pytest.approx(expected)
    assert document.metrics.cost_is_partial is True  # estimated usage is not a measurement


def test_a_text_session_derives_no_voice_usage() -> None:
    document = build_export(with_usage(snapshot(), ("m:input", 1000)), estimate=PRICED)
    assert all(not r.estimated for r in document.metrics.usage)


def record(kind: UsageKind, detail: str, quantity: float, *, estimated: bool) -> UsageRecord:
    return UsageRecord(
        session_id=SID,
        turn_id=None,
        kind=kind,
        quantity=quantity,
        unit_detail=detail,
        estimated=estimated,
    )


MEASURED_SPEECH = (
    record("stt_seconds", "nova-3", 95.5, estimated=False),
    record("tts_characters", "eleven_flash_v2_5", 13, estimated=False),
    record("media_participant_minutes", "daily", 3.5, estimated=False),
)


def test_a_voice_session_with_measured_speech_usage_has_a_complete_cost() -> None:
    taken = voice_snapshot().model_copy(update={"usage": MEASURED_SPEECH})
    metrics = build_export(taken, estimate=PRICED).metrics
    assert metrics.usage == MEASURED_SPEECH  # nothing derived on top
    assert metrics.estimated_marginal_cost_eur == pytest.approx(
        95.5 * 0.001 + 13 * 0.0001 + 3.5 * 0.01
    )
    assert metrics.cost_is_partial is False


def test_only_the_speech_kinds_nothing_measured_are_derived() -> None:
    taken = voice_snapshot().model_copy(update={"usage": MEASURED_SPEECH[:1]})
    metrics = build_export(taken, estimate=PRICED).metrics
    derived = {r.kind for r in metrics.usage if r.estimated}
    assert derived == {"tts_characters", "media_participant_minutes"}
    assert metrics.cost_is_partial is True  # something was not measured


def test_estimated_tokens_of_a_cut_generation_do_not_make_the_cost_partial() -> None:
    """Inferred from characters, flagged on the record, but nothing is missing (D44)."""
    taken = snapshot().model_copy(
        update={"usage": (record("llm_tokens", "m:input", 1000, estimated=True),)}
    )
    metrics = build_export(taken, estimate=PRICED).metrics
    assert metrics.estimated_marginal_cost_eur == pytest.approx(0.001)
    assert metrics.cost_is_partial is False
