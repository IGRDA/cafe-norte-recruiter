"""Pure codecs between records and rows. The only place that knows which columns a table has.

``*_params`` turns a record into the mapping a statement binds; ``*_from_row`` validates a row
(selected with exactly these column names) back into the record. ``Any`` stops here: a row is
``dict[str, Any]`` from the driver and a record on the way out."""

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from cafe_norte.domain.contracts import Booking, InterviewSlot, SessionState
from cafe_norte.observability.contracts import StageTiming, UsageRecord
from cafe_norte.persistence.contracts import EventRecord, Lease, TurnRecord

Row = Mapping[str, Any]

TURN_COLUMNS = (
    "turn_id, session_id, input_id, role, channel, language, text, delivered_text, "
    "interrupted, started_at, finished_at"
)
EVENT_COLUMNS = "session_id, seq, turn_id, kind, payload::text as payload_json, at"
SLOT_COLUMNS = (
    "s.slot_id, s.config_id, s.starts_at_utc, s.duration_minutes, "
    "(b.slot_id is not null) as reserved"
)
BOOKING_COLUMNS = (
    "b.slot_id, s.config_id, s.starts_at_utc, b.confirmation_id, b.idempotency_key, b.committed_at"
)
USAGE_COLUMNS = "session_id, turn_id, kind, quantity, unit_detail, estimated"
TIMING_COLUMNS = "session_id, turn_id, stage, milliseconds, source, tool_name"
LEASE_COLUMNS = "session_id, owner, generation, expires_at"


def _record[M: BaseModel](model: type[M], row: Row) -> M:
    """Validate the row's columns that the record declares; a join may carry more."""
    return model.model_validate({name: row[name] for name in model.model_fields if name in row})


def session_params(state: SessionState, *, access_hash: str) -> dict[str, Any]:
    return {
        "session_id": state.session_id,
        "state_json": state.model_dump_json(),
        "access_hash": access_hash,
        "created_at": state.created_at,
    }


def state_from_row(row: Row) -> SessionState:
    return SessionState.model_validate(row["state_json"])


def turn_params(turn: TurnRecord) -> dict[str, Any]:
    return turn.model_dump()


def turn_from_row(row: Row) -> TurnRecord:
    return _record(TurnRecord, row)


def event_params(event: EventRecord) -> dict[str, Any]:
    params = event.model_dump(exclude={"payload_json"})
    params["payload"] = event.payload_json
    return params


def event_from_row(row: Row) -> EventRecord:
    return _record(EventRecord, row)


def slot_params(slot: InterviewSlot) -> dict[str, Any]:
    return slot.model_dump(exclude={"status"})


def slot_from_row(row: Row) -> InterviewSlot:
    status = "reserved" if row["reserved"] else "available"
    return _record(InterviewSlot, {**row, "status": status})


def booking_from_row(row: Row) -> Booking:
    return _record(Booking, row)


def usage_params(usage: UsageRecord) -> dict[str, Any]:
    return usage.model_dump()


def usage_from_row(row: Row) -> UsageRecord:
    return _record(UsageRecord, row)


def timing_params(timing: StageTiming) -> dict[str, Any]:
    return timing.model_dump()


def timing_from_row(row: Row) -> StageTiming:
    return _record(StageTiming, row)


def lease_from_row(row: Row) -> Lease:
    return _record(Lease, row)
