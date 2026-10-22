"""The five booking conditions, the idempotency key and the simulated calendar rule."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from cafe_norte.domain.booking import idempotency_key, reservation_allowed, slot_offerable
from cafe_norte.domain.calendar import interview_slots
from cafe_norte.domain.contracts import (
    Booking,
    BriefTarget,
    CandidateRecord,
    ConfigId,
    Confirmation,
    ConfirmationId,
    Evidence,
    InterviewSlot,
    SessionId,
    SessionState,
    SlotId,
    SlotTarget,
    TurnId,
)
from cafe_norte.domain.result import Err, Ok
from tests.support.builders import CONFIGS, NOW

CHAMBERI = CONFIGS[ConfigId("chamberi_barista_v1")]
ARGANZUELA = CONFIGS[ConfigId("arganzuela_barista_v1")]
MADRID = ZoneInfo("Europe/Madrid")
INTENT = Evidence(source_turn_id=TurnId("t7"), text="Sí, quiero entrevista.")


def slot(
    slot_id: str = "s1", *, config_id: ConfigId = CHAMBERI.config_id, hours: int = 24
) -> InterviewSlot:
    return InterviewSlot(
        slot_id=SlotId(slot_id), config_id=config_id, starts_at_utc=NOW + timedelta(hours=hours)
    )


def state(**overrides: object) -> SessionState:
    base = dict(
        session_id=SessionId("s"),
        config_id=CHAMBERI.config_id,
        config_version="1",
        language="es",
        channel="text",
        created_at=NOW,
        candidate=CandidateRecord(revision=3),
        brief_confirmed_revision=3,
        schedule_intent=INTENT,
    )
    return SessionState.model_validate({**base, **overrides})


def confirmation(
    slot_id: str = "s1",
    *,
    brief_revision: int = 3,
    delivered: bool = True,
    status: str = "confirmed",
) -> Confirmation:
    return Confirmation(
        confirmation_id=ConfirmationId("c1"),
        target=SlotTarget(slot_id=SlotId(slot_id), brief_revision=brief_revision),
        presentation_text="¿Te la reservo?",
        presented_turn_id=TurnId("t8"),
        fully_delivered=delivered,
        response_turn_id=TurnId("t9"),
        status=status,
    )


# ---- reservation_allowed -------------------------------------------------------------------------


def test_every_condition_met_yields_the_slot_target() -> None:
    result = reservation_allowed(state(), slot(), confirmation(), now=NOW)
    assert result == Ok(SlotTarget(slot_id=SlotId("s1"), brief_revision=3))


def test_each_condition_refuses_with_its_own_reason_in_order() -> None:
    cases = [
        ((state(lifecycle="completed"), slot(), confirmation()), "session_not_active"),
        ((state(brief_confirmed_revision=2), slot(), confirmation()), "brief_not_confirmed"),
        ((state(brief_confirmed_revision=None), slot(), confirmation()), "brief_not_confirmed"),
        ((state(schedule_intent=None), slot(), confirmation()), "no_schedule_intent"),
        ((state(), slot(), None), "confirmation_missing"),
        ((state(), slot(), confirmation(delivered=False)), "confirmation_not_delivered"),
        ((state(), slot(), confirmation("other")), "confirmation_mismatch"),
        ((state(), slot(), confirmation(brief_revision=2)), "confirmation_mismatch"),
        ((state(), slot(), confirmation(status="pending")), "confirmation_mismatch"),
        ((state(), slot(config_id=ARGANZUELA.config_id), confirmation()), "slot_other_store"),
        ((state(), slot(hours=-1), confirmation()), "slot_in_past"),
        ((state(), slot(hours=0), confirmation()), "slot_in_past"),
        (
            (state(), slot().model_copy(update={"status": "reserved"}), confirmation()),
            "slot_unavailable",
        ),
    ]
    for (s, sl, c), reason in cases:
        assert reservation_allowed(s, sl, c, now=NOW) == Err(reason), reason


def test_a_brief_confirmation_is_not_a_slot_confirmation() -> None:
    brief = confirmation().model_copy(update={"target": BriefTarget(revision=3)})
    assert reservation_allowed(state(), slot(), brief, now=NOW) == Err("confirmation_mismatch")


def test_a_session_books_at_most_once() -> None:
    booked = state(
        booking=Booking(
            slot_id=SlotId("s0"),
            config_id=CHAMBERI.config_id,
            starts_at_utc=NOW + timedelta(hours=2),
            confirmation_id=ConfirmationId("c0"),
            idempotency_key="k0",
            committed_at=NOW,
        )
    )
    assert reservation_allowed(booked, slot(), confirmation(), now=NOW) == Err("already_booked")


def test_work_authorization_and_flags_are_not_gates() -> None:
    from cafe_norte.domain.contracts import ReviewFlag

    flagged = state(
        review_flags=(ReviewFlag(kind="work_authorization", turn_id=TurnId("t3"), note="no"),)
    )
    assert isinstance(reservation_allowed(flagged, slot(), confirmation(), now=NOW), Ok)


def test_slot_offerable_is_the_slot_half_of_the_rule() -> None:
    assert slot_offerable(state(), slot(), now=NOW) is None
    assert (
        slot_offerable(state(), slot(config_id=ARGANZUELA.config_id), now=NOW) == "slot_other_store"
    )
    assert slot_offerable(state(), slot(hours=-1), now=NOW) == "slot_in_past"


def test_idempotency_key_binds_session_and_confirmation_deterministically() -> None:
    key = idempotency_key(state(), confirmation())
    assert key == idempotency_key(state(), confirmation())
    assert len(key) == 64
    assert key != idempotency_key(state(session_id=SessionId("other")), confirmation())
    other = confirmation().model_copy(update={"confirmation_id": ConfirmationId("c2")})
    assert key != idempotency_key(state(), other)


# ---- interview_slots -----------------------------------------------------------------------------


def test_slots_cover_the_next_seven_days_on_shift_days_at_the_configured_times() -> None:
    slots = interview_slots(CHAMBERI, after=NOW)
    locals_ = [s.starts_at_utc.astimezone(MADRID) for s in slots]
    assert all(s.config_id == CHAMBERI.config_id and s.duration_minutes == 30 for s in slots)
    assert all(s.status == "available" for s in slots)
    assert all(t.strftime("%H:%M") in CHAMBERI.interview_times for t in locals_)
    assert all(t.weekday() != 6 for t in locals_)  # Chamberí has no Sunday shift
    assert locals_ == sorted(locals_)
    assert locals_[0].date() == NOW.astimezone(MADRID).date()  # today's 17:00 is still ahead
    assert locals_[0].strftime("%H:%M") == "17:00"
    assert (locals_[-1].date() - locals_[0].date()).days <= 7
    # Tue 20 (17:00 only) + Wed..Sat (2 each) + Mon 26, Tue 27 (2 each): 1 + 8 + 4
    assert len(slots) == 13


def test_slot_ids_are_deterministic_and_name_the_store_the_day_and_the_local_time() -> None:
    first = interview_slots(CHAMBERI, after=NOW)
    again = interview_slots(CHAMBERI, after=NOW)
    assert first == again
    assert first[0].slot_id == "chamberi_barista_v1-2026-10-20-1700"
    assert first[1].slot_id == "chamberi_barista_v1-2026-10-21-1030"
    assert first[1].starts_at_utc == datetime(2026, 10, 21, 8, 30, tzinfo=UTC)  # CEST is UTC+2


def test_nothing_in_the_past_and_arganzuela_keeps_its_own_days() -> None:
    late = datetime(2026, 10, 20, 16, tzinfo=UTC)  # 18:00 in Madrid: today's slots are gone
    assert all(s.starts_at_utc > late for s in interview_slots(CHAMBERI, after=late))
    assert interview_slots(CHAMBERI, after=late)[0].slot_id.endswith("2026-10-21-1030")
    weekend = [
        s
        for s in interview_slots(ARGANZUELA, after=NOW)
        if s.starts_at_utc.astimezone(MADRID).weekday() == 6
    ]
    assert weekend, "Arganzuela opens on Sundays"
    assert all(s.config_id == ARGANZUELA.config_id for s in interview_slots(ARGANZUELA, after=NOW))
