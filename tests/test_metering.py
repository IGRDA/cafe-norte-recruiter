"""What one call used of the speech providers, as measured (D44). Pure: times are arguments."""

from datetime import UTC, datetime, timedelta

from cafe_norte.domain.contracts import SessionId
from cafe_norte.voice.metering import SpeechMeter

SID = SessionId("s1")
T0 = datetime(2026, 10, 21, 16, 6, tzinfo=UTC)


def quantities(meter: SpeechMeter, at: datetime) -> dict[str, float]:
    records = meter.records(SID, at=at, stt_model="nova-3", tts_model="eleven_flash_v2_5")
    assert all(not r.estimated and r.turn_id is None and r.session_id == SID for r in records)
    return {f"{r.kind}:{r.unit_detail}": r.quantity for r in records}


def test_heard_seconds_and_spoken_characters_add_up() -> None:
    meter = SpeechMeter()
    meter.heard(1.5)
    meter.heard(2.25)
    meter.spoke(40)
    meter.spoke(2)
    used = quantities(meter, T0)
    assert used["stt_seconds:nova-3"] == 3.75
    assert used["tts_characters:eleven_flash_v2_5"] == 42


def test_room_minutes_count_the_bot_and_the_candidate_each_while_present() -> None:
    meter = SpeechMeter()
    meter.entered("bot", T0)
    meter.entered("candidate", T0 + timedelta(seconds=30))
    meter.left("candidate", T0 + timedelta(minutes=4, seconds=30))
    # The bot is still in the room when the call ends: it counts until then.
    used = quantities(meter, T0 + timedelta(minutes=5))
    assert used["media_participant_minutes:daily"] == 5 + 4


def test_a_participant_who_comes_back_counts_each_stay() -> None:
    meter = SpeechMeter()
    meter.entered("candidate", T0)
    meter.left("candidate", T0 + timedelta(minutes=1))
    meter.entered("candidate", T0 + timedelta(minutes=2))
    meter.left("candidate", T0 + timedelta(minutes=3))
    meter.left("candidate", T0 + timedelta(minutes=9))  # a second leave changes nothing
    assert quantities(meter, T0 + timedelta(minutes=10))["media_participant_minutes:daily"] == 2


def test_a_call_that_never_connected_measured_nothing() -> None:
    assert set(quantities(SpeechMeter(), T0).values()) == {0}
