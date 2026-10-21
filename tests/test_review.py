"""Follow-up flags: one function adds them, at most one per turn."""

from datetime import UTC, datetime

from cafe_norte.domain.contracts import ConfigId, SessionId, SessionState, TurnId
from cafe_norte.domain.review import add_followup, has_followup

STATE = SessionState(
    session_id=SessionId("s"),
    config_id=ConfigId("c"),
    config_version="1",
    language="es",
    channel="text",
    created_at=datetime(2026, 10, 20, tzinfo=UTC),
)


def test_a_follow_up_is_added_once_per_turn_and_kept_across_turns() -> None:
    assert not has_followup(STATE)
    once = add_followup(STATE, TurnId("t1"), "quiero hablar con una persona")
    assert has_followup(once)
    assert add_followup(once, TurnId("t1"), "otra vez") == once
    twice = add_followup(once, TurnId("t2"), "¿hay parking?")
    assert [(f.turn_id, f.note) for f in twice.review_flags] == [
        ("t1", "quiero hablar con una persona"),
        ("t2", "¿hay parking?"),
    ]
