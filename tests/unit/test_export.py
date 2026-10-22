"""The export document: one snapshot in, one document out; the confirmation history and the
session's end come from the journaled ``state_updated`` events."""

import json
from datetime import timedelta
from functools import partial

import pytest
from hypothesis import given
from hypothesis import strategies as st

from cafe_norte.domain.contracts import (
    ReviewWaived,
    TurnId,
)
from cafe_norte.observability.contracts import (
    Price,
    PriceTable,
    UsageKind,
    UsageRecord,
)
from cafe_norte.observability.cost import estimate
from cafe_norte.persistence.contracts import EventRecord, SessionSnapshot
from cafe_norte.persistence.export import (
    ExportDocument,
    brief_text,
    build_export,
    confirmations_from_events,
    ended_at,
)
from tests.support.builders import NOW, STAMP
from tests.support.exports import BRIEF, PHONE, SID, journal, snapshot, state_updated
from tests.support.strategies import events, instants, session_states, timings, turns, usage


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
    assert document.versions == STAMP
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


# ---- laws of build_export ------------------------------------------------------------------------

snapshots = st.builds(
    SessionSnapshot,
    state=session_states(),
    turns=st.lists(turns, max_size=4).map(tuple),
    confirmations=st.just(()),
    events=st.lists(events, max_size=4).map(tuple),
    usage=st.lists(usage, max_size=4).map(tuple),
    timings=st.lists(timings, max_size=3).map(tuple),
    versions=st.just(STAMP),
    taken_at=instants,
)


@given(snapshots)
def test_any_export_survives_its_own_json(snapshot: SessionSnapshot) -> None:
    document = build_export(snapshot)

    assert ExportDocument.model_validate_json(document.model_dump_json()) == document


@given(snapshots)
def test_an_export_carries_the_record_and_counts_the_candidates_turns(
    snapshot: SessionSnapshot,
) -> None:
    document = build_export(snapshot)

    assert document.candidate == snapshot.state.candidate
    assert document.booking == snapshot.state.booking
    assert document.metrics.turns == sum(1 for t in snapshot.turns if t.role == "user")
    assert document.metrics.cost_is_partial  # no price table, so never a complete cost
