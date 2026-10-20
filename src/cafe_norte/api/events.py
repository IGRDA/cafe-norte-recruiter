"""Server-Sent Events encoding and replay."""

from collections.abc import AsyncIterator

from cafe_norte.api.contracts import SessionEvent
from cafe_norte.domain.contracts import SessionId
from cafe_norte.persistence.contracts import Events


def encode(event: SessionEvent) -> bytes:
    """``id: <seq>\\nevent: <type>\\ndata: <json>\\n\\n``."""
    raise NotImplementedError


def stream(events: Events, session_id: SessionId, *, after_seq: int) -> AsyncIterator[bytes]:
    """Persisted events after ``after_seq``, then live ones; heartbeat comments keep Cloud Run's
    600-second timeout from idling the connection."""
    raise NotImplementedError
