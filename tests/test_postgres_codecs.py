"""The pure codecs between records and rows: what goes into a statement comes back from its
row unchanged. Offline; the SQL that carries the rows is exercised by the contract on Postgres."""

import json
from datetime import timedelta

from hypothesis import given
from hypothesis import strategies as st

from cafe_norte.domain.contracts import (
    Booking,
    CandidateRecord,
    ConfigId,
    ConfirmationId,
    InterviewSlot,
    SessionId,
    SessionState,
    SlotId,
    TurnId,
)
from cafe_norte.observability.contracts import StageTiming, UsageRecord
from cafe_norte.persistence.contracts import EventRecord, TurnRecord
from cafe_norte.persistence.postgres import codecs
from tests.support.builders import NOW

text = st.text(min_size=1, max_size=20)
instants = st.integers(min_value=0, max_value=10**7).map(lambda s: NOW + timedelta(seconds=s))

turns = st.builds(
    TurnRecord,
    turn_id=text.map(TurnId),
    session_id=text.map(SessionId),
    input_id=text,
    role=st.sampled_from(["user", "assistant"]),
    channel=st.sampled_from(["voice", "text"]),
    language=st.sampled_from(["es", "en"]),
    text=st.text(max_size=40),
    delivered_text=st.none() | st.text(max_size=40),
    interrupted=st.booleans(),
    started_at=instants,
    finished_at=st.none() | instants,
)
events = st.builds(
    EventRecord,
    session_id=text.map(SessionId),
    turn_id=st.none() | text.map(TurnId),
    seq=st.integers(min_value=1, max_value=10**6),
    kind=text,
    payload_json=st.dictionaries(text, st.integers()).map(json.dumps),
    at=instants,
)
slots = st.builds(
    InterviewSlot,
    slot_id=text.map(SlotId),
    config_id=text.map(ConfigId),
    starts_at_utc=instants,
    duration_minutes=st.integers(min_value=1, max_value=120),
    status=st.sampled_from(["available", "reserved"]),
)
bookings = st.builds(
    Booking,
    slot_id=text.map(SlotId),
    config_id=text.map(ConfigId),
    starts_at_utc=instants,
    confirmation_id=text.map(ConfirmationId),
    idempotency_key=text,
    committed_at=instants,
)
usage = st.builds(
    UsageRecord,
    session_id=text.map(SessionId),
    turn_id=st.none() | text.map(TurnId),
    kind=st.sampled_from(["llm_tokens", "tts_characters", "stt_seconds"]),
    quantity=st.floats(min_value=0, max_value=1e6, allow_nan=False),
    unit_detail=text,
    estimated=st.booleans(),
)
timings = st.builds(
    StageTiming,
    session_id=text.map(SessionId),
    turn_id=text.map(TurnId),
    stage=st.sampled_from(["llm_total", "tool", "text_total"]),
    milliseconds=st.integers(min_value=0, max_value=10**6),
    source=st.sampled_from(["server", "browser", "server_proxy"]),
    tool_name=st.text(max_size=10),
)


@given(turns)
def test_turn_round_trip(turn: TurnRecord) -> None:
    assert codecs.turn_from_row(codecs.turn_params(turn)) == turn


@given(events)
def test_event_round_trip_through_the_jsonb_payload(event: EventRecord) -> None:
    params = codecs.event_params(event)
    row = {**params, "payload_json": json.dumps(json.loads(params["payload"]))}
    assert codecs.event_from_row(row) == event


@given(slots)
def test_slot_round_trip_derives_the_status_from_the_booking(slot: InterviewSlot) -> None:
    row = {**codecs.slot_params(slot), "reserved": slot.status == "reserved"}
    assert codecs.slot_from_row(row) == slot


@given(bookings)
def test_booking_round_trip(booking: Booking) -> None:
    assert codecs.booking_from_row(booking.model_dump()) == booking


@given(usage)
def test_usage_round_trip(record: UsageRecord) -> None:
    assert codecs.usage_from_row(codecs.usage_params(record)) == record


@given(timings)
def test_timing_round_trip(timing: StageTiming) -> None:
    assert codecs.timing_from_row(codecs.timing_params(timing)) == timing


def test_session_state_round_trip_through_the_document() -> None:
    state = SessionState(
        session_id=SessionId("s1"),
        config_id=ConfigId("c"),
        config_version="1",
        language="en",
        channel="voice",
        created_at=NOW,
        lifecycle="completed",
        outcome="reserved",
        candidate=CandidateRecord(revision=3),
        brief_confirmed_revision=3,
        booking=Booking(
            slot_id=SlotId("x"),
            config_id=ConfigId("c"),
            starts_at_utc=NOW,
            confirmation_id=ConfirmationId("k"),
            idempotency_key="key",
            committed_at=NOW,
        ),
    )
    params = codecs.session_params(state, access_hash="h")
    assert params["created_at"] == NOW and params["access_hash"] == "h"
    assert codecs.state_from_row({"state_json": json.loads(params["state_json"])}) == state
