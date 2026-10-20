"""Session cookie ownership and the demo code."""

from datetime import UTC, datetime

from cafe_norte.api.access import AccessGate, gate_from_env
from cafe_norte.domain.contracts import SessionId


def test_a_cookie_proves_ownership_only_with_the_right_secret() -> None:
    gate = AccessGate(code=None, secret=b"a")
    cookie = gate.issue_session_cookie(SessionId("abc"))
    assert gate.session_from_cookie(cookie) == "abc"
    assert AccessGate(code=None, secret=b"b").session_from_cookie(cookie) is None
    assert gate.session_from_cookie("abc.deadbeef") is None
    assert gate.session_from_cookie(None) is None
    assert gate.session_from_cookie("garbage") is None


def test_the_demo_code_is_optional_locally() -> None:
    assert AccessGate(code=None, secret=b"a").check_code("anything")
    gate = AccessGate(code="cafe", secret=b"a")
    assert gate.check_code("cafe") and not gate.check_code("latte")


def test_resume_tokens_are_long_and_only_their_hash_is_stored() -> None:
    token, token_hash = AccessGate(code=None, secret=b"a").new_resume_token()
    assert len(token) >= 32 and len(token_hash) == 64 and token not in token_hash
    assert AccessGate.expiry(datetime(2026, 1, 1, tzinfo=UTC)).day == 8


def test_gate_from_env_reads_code_and_secret() -> None:
    gate = gate_from_env({"CAFE_NORTE_ACCESS_CODE": "x", "CAFE_NORTE_COOKIE_SECRET": "s"})
    assert gate.check_code("x") and not gate.check_code("")
    assert gate_from_env({}).check_code("")
