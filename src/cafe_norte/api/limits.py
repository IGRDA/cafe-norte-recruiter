"""Request ceilings for the hosted demo: access attempts and session starts per client IP,
and sessions per day across clients. The default app enables them when an access code is set.

The per-IP counters live in process memory: one container serves the demo, and a restart only
forgives. The daily count includes only sessions still in the store and survives restarts.
It is checked before creation without a shared lock, so concurrent starts can exceed it."""

from collections import deque
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field


class RequestLimits(BaseModel):
    model_config = ConfigDict(frozen=True)

    access_attempts_per_minute: int = Field(default=15, ge=1)
    session_starts_per_hour: int = Field(default=9, ge=1)
    sessions_per_day: int = Field(default=150, ge=1)

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "RequestLimits":
        """Defaults unless ``CAFE_NORTE_ACCESS_ATTEMPTS_PER_MINUTE``,
        ``CAFE_NORTE_SESSION_STARTS_PER_HOUR`` or ``CAFE_NORTE_SESSIONS_PER_DAY`` say otherwise."""
        names = {
            "access_attempts_per_minute": "CAFE_NORTE_ACCESS_ATTEMPTS_PER_MINUTE",
            "session_starts_per_hour": "CAFE_NORTE_SESSION_STARTS_PER_HOUR",
            "sessions_per_day": "CAFE_NORTE_SESSIONS_PER_DAY",
        }
        return cls.model_validate(
            {field: env[name] for field, name in names.items() if env.get(name)}
        )


class SlidingWindow:
    """At most ``limit`` hits per key within any ``seconds``. A refused hit is not counted, so a
    client that keeps trying gets back in as its oldest hits age out. Keys with no hit inside
    the window are swept once per window, so memory follows recent clients only."""

    def __init__(self, *, limit: int, seconds: float) -> None:
        self._limit = limit
        self._seconds = seconds
        self._hits: dict[str, deque[float]] = {}
        self._swept_at = float("-inf")

    @property
    def tracked(self) -> int:
        return len(self._hits)

    def hit(self, key: str, *, now: float) -> bool:
        if now - self._swept_at >= self._seconds:
            self._sweep(now)
        hits = self._hits.setdefault(key, deque())
        while hits and hits[0] <= now - self._seconds:
            hits.popleft()
        if len(hits) >= self._limit:
            return False
        hits.append(now)
        return True

    def _sweep(self, now: float) -> None:
        self._hits = {k: h for k, h in self._hits.items() if h and h[-1] > now - self._seconds}
        self._swept_at = now
