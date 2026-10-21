"""Emit structured JSON lines to stdout."""

import json
import re
import sys
from typing import Any, TextIO

from cafe_norte.observability.contracts import StructuredEvent

# Keys that would carry what a candidate or Ana said. A log line is metadata only.
TRANSCRIPT_KEYS = frozenset({"text", "transcript", "content", "message"})

# Most specific first: a card or IBAN is digits too, and must not be read as a phone.
_MASKS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern), mask)
    for pattern, mask in (
        (r"(?i)\b(?:api[_-]?key|token|secret|password)\s*[=:]\s*\S+", "[secret]"),
        (r"(?i)\bBearer\s+[\w.~+/=-]+", "[secret]"),
        (r"\b(?:sk|pk)-[\w-]{8,}", "[secret]"),
        (r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", "[email]"),
        (r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,3})?\b", "[iban]"),
        (r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)", "[card]"),
        (r"\b\d{8}[A-Za-z]\b|\b[XYZxyz]\d{7}[A-Za-z]\b", "[id]"),
        (r"(?<!\d)(?:(?:\+|00)34[ .-]?)?[6-9](?:[ .-]?\d){8}(?!\d)", "[phone]"),
    )
)


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


def redact(text: str, *, limit: int = 2000) -> str:
    """Replace emails, Spanish phones and identifiers, IBANs, cards and secrets; truncate.
    Masking comes first so a cut can never leave half an email behind."""
    for pattern, mask in _MASKS:
        text = pattern.sub(mask, text)
    return text if len(text) <= limit else text[: limit - 1] + "…"


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
