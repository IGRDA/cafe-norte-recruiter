"""The pure codecs between records and rows: what goes into a statement comes back from its
row unchanged. Offline; the SQL that carries the rows is exercised by the contract on Postgres."""

import json

from hypothesis import given

from cafe_norte.domain.contracts import (
    Booking,
    CandidateRecord,
    ConfigId,
    ConfirmationId,
    InterviewSlot,
    SessionId,
    SessionState,
    SlotId,
)
from cafe_norte.observability.contracts import StageTiming, UsageRecord
from cafe_norte.persistence.contracts import EventRecord, TurnRecord
from cafe_norte.persistence.postgres import codecs
from tests.support.builders import NOW
from tests.support.strategies import bookings, events, slots, timings, turns, usage


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
