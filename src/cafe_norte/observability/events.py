"""Emit structured JSON lines to stdout."""

import json
import sys
from typing import Any, TextIO

from cafe_norte.domain.contracts import Channel, SessionId, StoreConfiguration, TurnId
from cafe_norte.errors import Language
from cafe_norte.observability.contracts import Span, StructuredEvent
from cafe_norte.observability.fakes import NullSpan
from cafe_norte.observability.redaction import redact

# Keys that would carry what a candidate or Ana said. A log line is metadata only.
TRANSCRIPT_KEYS = frozenset({"text", "transcript", "content", "message"})


def emit(event: StructuredEvent, stream: TextIO | None = None) -> None:
    """Write one JSON line keyed by session and turn. The envelope wins over the payload."""
    envelope: dict[str, Any] = {
        "at": event.at.isoformat(),
        "severity": event.severity,
        "session_id": event.session_id,
        "turn_id": event.turn_id,
        "event": event.event,
    }
    payload = _masked(event.payload)
    line = envelope | {key: value for key, value in payload.items() if key not in envelope}
    out = stream if stream is not None else sys.stdout
    out.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")
    out.flush()


def _masked(value: Any) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        for key in value:
            if str(key).lower() in TRANSCRIPT_KEYS:
                raise ValueError(f"payload key {key!r} looks like transcript text")
        return {key: _masked(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_masked(item) for item in value]
    return value


class StdoutTelemetry:
    """Events as JSON lines on stdout, no traces: what a run without Langfuse keys uses."""

    def emit(self, event: StructuredEvent) -> None:
        emit(event)

    def turn(
        self,
        *,
        session_id: SessionId,
        turn_id: TurnId,
        configuration: StoreConfiguration,
        channel: Channel,
        language: Language,
    ) -> Span:
        return NullSpan()
