"""Masking for free text that leaves the database: log lines, trace content, tool arguments in
the journal. Pure, so any module may call it."""

import re

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


def redact(text: str, *, limit: int = 2000) -> str:
    """Replace emails, Spanish phones and identifiers, IBANs, cards and secrets; truncate.
    Masking comes first so a cut can never leave half an email behind."""
    for pattern, mask in _MASKS:
        text = pattern.sub(mask, text)
    return text if len(text) <= limit else text[: limit - 1] + "…"
