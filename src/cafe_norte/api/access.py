"""Demo access code, session cookies and resume tokens."""

import hashlib
import hmac
import secrets
from collections.abc import Mapping
from datetime import datetime, timedelta

from cafe_norte.domain.contracts import SessionId

SESSION_COOKIE = "cafe_norte_session"
ACCESS_COOKIE = "cafe_norte_access"


class AccessGate:
    """Shared code check, HttpOnly SameSite cookies, 256-bit resume tokens stored as hashes.

    The session cookie is ``<session_id>.<hmac>``: ownership of a session is proven by a
    signature only this process's secret can produce."""

    def __init__(self, *, code: str | None, secret: bytes) -> None:
        self._code = code or None
        self._secret = secret

    @property
    def requires_code(self) -> bool:
        return self._code is not None

    def check_code(self, supplied: str) -> bool:
        return self._code is None or hmac.compare_digest(self._code, supplied)

    def issue_access_cookie(self) -> str:
        """A signature over the code, never the code itself; valid until the code rotates."""
        return self._sign(f"access:{self._code or ''}")

    def access_cookie_valid(self, cookie: str | None) -> bool:
        if self._code is None:
            return True
        return bool(cookie) and hmac.compare_digest(self.issue_access_cookie(), cookie or "")

    def issue_session_cookie(self, session_id: SessionId) -> str:
        return f"{session_id}.{self._sign(session_id)}"

    def session_from_cookie(self, cookie: str | None) -> SessionId | None:
        if not cookie or "." not in cookie:
            return None
        session_id, signature = cookie.rsplit(".", 1)
        if not hmac.compare_digest(self._sign(session_id), signature):
            return None
        return SessionId(session_id)

    def new_resume_token(self) -> tuple[str, str]:
        """``(token, token_hash)``; only the hash is stored."""
        token = secrets.token_urlsafe(32)
        return token, self.token_hash(token)

    @staticmethod
    def token_hash(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    @staticmethod
    def expiry(now: datetime, *, days: int = 7) -> datetime:
        return now + timedelta(days=days)

    def _sign(self, session_id: str) -> str:
        return hmac.new(self._secret, session_id.encode(), hashlib.sha256).hexdigest()


def gate_from_env(env: Mapping[str, str]) -> AccessGate:
    """An empty secret means a fresh one per process: cookies die with a restart, locally."""
    secret = env.get("CAFE_NORTE_COOKIE_SECRET") or secrets.token_hex(32)
    return AccessGate(code=env.get("CAFE_NORTE_ACCESS_CODE") or None, secret=secret.encode())
