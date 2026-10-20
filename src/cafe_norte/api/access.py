"""Demo access code, session cookies and resume tokens."""

from collections.abc import Mapping
from datetime import datetime

from cafe_norte.domain.contracts import SessionId


class AccessGate:
    """Shared code check, HttpOnly SameSite cookies, 256-bit resume tokens stored as hashes."""

    def __init__(self, *, code: str | None, secret: bytes) -> None:
        raise NotImplementedError

    def check_code(self, supplied: str) -> bool:
        raise NotImplementedError

    def issue_session_cookie(self, session_id: SessionId) -> str:
        raise NotImplementedError

    def session_from_cookie(self, cookie: str | None) -> SessionId | None:
        raise NotImplementedError

    def new_resume_token(self) -> tuple[str, str]:
        """``(token, token_hash)``; only the hash is stored."""
        raise NotImplementedError

    @staticmethod
    def expiry(now: datetime, *, days: int = 7) -> datetime:
        raise NotImplementedError


def gate_from_env(env: Mapping[str, str]) -> AccessGate:
    raise NotImplementedError
