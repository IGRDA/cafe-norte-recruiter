"""Emit structured JSON lines to stdout."""

from cafe_norte.observability.contracts import StructuredEvent


def emit(event: StructuredEvent) -> None:
    raise NotImplementedError


def redact(text: str, *, limit: int = 2000) -> str:
    """Replace emails, Spanish phones and identifiers, IBANs, cards and secrets; truncate."""
    raise NotImplementedError
