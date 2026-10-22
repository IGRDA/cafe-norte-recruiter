"""Hypothesis strategies for the domain's values, built valid, shared by the property tests."""

import json
from datetime import date, timedelta
from typing import Any, get_args

from hypothesis import strategies as st

from cafe_norte.domain.contracts import (
    Booking,
    CandidateFieldName,
    CandidatePatch,
    CandidateRecord,
    Captured,
    ConfigId,
    ConfirmationId,
    Confirmed,
    Declined,
    Evidence,
    FieldState,
    InterviewSlot,
    Lifecycle,
    Outcome,
    ReviewFlag,
    SessionId,
    SessionState,
    ShiftId,
    SlotId,
    TurnId,
    Unknown,
    Unset,
    Weekday,
)
from cafe_norte.errors import Language
from cafe_norte.observability.contracts import StageTiming, UsageRecord
from cafe_norte.persistence.contracts import EventRecord, TurnRecord
from tests.support.builders import NOW

# ---- scalars -------------------------------------------------------------------------------------

text = st.text(min_size=1, max_size=20)
languages: st.SearchStrategy[Language] = st.sampled_from(get_args(Language))
instants = st.integers(min_value=0, max_value=10**7).map(lambda s: NOW + timedelta(seconds=s))
turn_ids = text.map(TurnId)
confirmation_ids = text.map(ConfirmationId)
evidence = st.builds(Evidence, source_turn_id=turn_ids, text=text)

# ---- the field algebra and the candidate record --------------------------------------------------


def field_states(values: st.SearchStrategy[str]) -> st.SearchStrategy[FieldState[str]]:
    """Every state a text field can be in, holding ``values``."""
    return st.one_of(
        st.just(Unset()),
        st.builds(Captured[str], value=values, evidence=evidence),
        st.builds(
            Confirmed[str], value=values, evidence=evidence, confirmation_id=confirmation_ids
        ),
        st.builds(Unknown, attempts=st.integers(min_value=0, max_value=5)),
        st.builds(Declined, source_turn_id=turn_ids),
    )


SHIFTS = ("morning", "afternoon", "evening")
FIELD_VALUES: dict[CandidateFieldName, st.SearchStrategy[Any]] = {
    "name": st.text(min_size=1, max_size=30).map(str.strip).filter(bool),
    "contact_phone": st.from_regex(r"\+34[6-7]\d{8}", fullmatch=True),
    "interest": st.sampled_from(["yes", "unsure", "no"]),
    "work_authorization": st.sampled_from(["yes", "no", "unsure"]),
    "availability_days": st.frozensets(st.sampled_from(get_args(Weekday)), min_size=1),
    "availability_shifts": st.frozensets(st.sampled_from(SHIFTS).map(ShiftId), min_size=1),
    "hours_per_week": st.integers(min_value=1, max_value=60),
    "earliest_start_date": st.dates(date(2026, 10, 20), date(2027, 12, 31)),
    "experience": st.text(max_size=40).map(str.strip),
}


def _field_document(values: st.SearchStrategy[Any]) -> st.SearchStrategy[dict[str, Any]]:
    """A field state as the record validates it, so each value gets its declared type."""
    return st.one_of(
        st.just({"status": "unset"}),
        st.builds(lambda v, e: {"status": "captured", "value": v, "evidence": e}, values, evidence),
        st.builds(
            lambda v, e, c: {
                "status": "confirmed",
                "value": v,
                "evidence": e,
                "confirmation_id": c,
            },
            values,
            evidence,
            confirmation_ids,
        ),
        st.builds(lambda n: {"status": "unknown", "attempts": n}, st.integers(0, 5)),
        st.builds(lambda t: {"status": "declined", "source_turn_id": t}, turn_ids),
    )


@st.composite
def candidate_records(draw: st.DrawFn) -> CandidateRecord:
    fields = {name: draw(_field_document(values)) for name, values in FIELD_VALUES.items()}
    notes = tuple(draw(st.lists(text, max_size=2)))
    revision = draw(st.integers(min_value=0, max_value=50))
    return CandidateRecord.model_validate({"revision": revision, "notes": notes, **fields})


@st.composite
def patches(draw: st.DrawFn) -> CandidatePatch:
    """A validated patch: each field it mentions is a value, declined or unknown, never two."""
    mentioned = draw(st.lists(st.sampled_from(list(FIELD_VALUES)), unique=True, max_size=4))
    values: dict[str, Any] = {}
    declined: set[CandidateFieldName] = set()
    unknown: set[CandidateFieldName] = set()
    for name in mentioned:
        kind = draw(st.sampled_from(["value", "declined", "unknown"]))
        if kind == "value":
            values[name] = draw(FIELD_VALUES[name])
        else:
            (declined if kind == "declined" else unknown).add(name)
    note = draw(st.none() | text)
    return CandidatePatch.model_validate(
        {**values, "declined": declined, "unknown": unknown, "note": note}
    )


# ---- sessions and their records ------------------------------------------------------------------

bookings = st.builds(
    Booking,
    slot_id=text.map(SlotId),
    config_id=text.map(ConfigId),
    starts_at_utc=instants,
    confirmation_id=confirmation_ids,
    idempotency_key=text,
    committed_at=instants,
)
review_flags = st.builds(
    ReviewFlag,
    kind=st.sampled_from(get_args(ReviewFlag.model_fields["kind"].annotation)),
    turn_id=turn_ids,
    note=st.text(max_size=20),
)


@st.composite
def session_states(draw: st.DrawFn) -> SessionState:
    """Any session, in any lifecycle, with any record, booking and review flags."""
    return SessionState(
        session_id=draw(text.map(SessionId)),
        config_id=draw(text.map(ConfigId)),
        config_version=draw(text),
        language=draw(languages),
        channel=draw(st.sampled_from(["voice", "text"])),
        created_at=draw(instants),
        lifecycle=draw(st.sampled_from(get_args(Lifecycle))),
        outcome=draw(st.none() | st.sampled_from(get_args(Outcome))),
        candidate=draw(candidate_records()),
        brief_confirmed_revision=draw(st.none() | st.integers(0, 50)),
        booking=draw(st.none() | bookings),
        review_flags=tuple(draw(st.lists(review_flags, max_size=3))),
        active_seconds=draw(st.floats(min_value=0, max_value=3600, allow_nan=False)),
        turn_count=draw(st.integers(min_value=0, max_value=100)),
    )


turns = st.builds(
    TurnRecord,
    turn_id=turn_ids,
    session_id=text.map(SessionId),
    input_id=text,
    role=st.sampled_from(["user", "assistant"]),
    channel=st.sampled_from(["voice", "text"]),
    language=languages,
    text=st.text(max_size=40),
    delivered_text=st.none() | st.text(max_size=40),
    interrupted=st.booleans(),
    started_at=instants,
    finished_at=st.none() | instants,
)
events = st.builds(
    EventRecord,
    session_id=text.map(SessionId),
    turn_id=st.none() | turn_ids,
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
usage = st.builds(
    UsageRecord,
    session_id=text.map(SessionId),
    turn_id=st.none() | turn_ids,
    kind=st.sampled_from(["llm_tokens", "tts_characters", "stt_seconds"]),
    quantity=st.floats(min_value=0, max_value=1e6, allow_nan=False),
    unit_detail=text,
    estimated=st.booleans(),
)
timings = st.builds(
    StageTiming,
    session_id=text.map(SessionId),
    turn_id=turn_ids,
    stage=st.sampled_from(["llm_total", "tool", "text_total"]),
    milliseconds=st.integers(min_value=0, max_value=10**6),
    source=st.sampled_from(["server", "browser", "server_proxy"]),
    tool_name=st.text(max_size=10),
)
