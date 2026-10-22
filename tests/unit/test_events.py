"""Structured events: one JSON line, metadata only, free text redacted."""

import io
import json
from datetime import UTC, datetime
from typing import Any

import pytest

from cafe_norte.domain.contracts import SessionId, TurnId
from cafe_norte.observability.contracts import EventName, Severity, StructuredEvent
from cafe_norte.observability.events import emit
from cafe_norte.observability.redaction import redact

NOW = datetime(2026, 10, 21, 12, 30, tzinfo=UTC)
T1 = TurnId("t1")


def event(
    payload: dict[str, Any],
    *,
    name: EventName = "turn_failed",
    severity: Severity = "WARNING",
    turn: TurnId | None = T1,
) -> StructuredEvent:
    return StructuredEvent(
        at=NOW,
        severity=severity,
        session_id=SessionId("s1"),
        turn_id=turn,
        event=name,
        payload=payload,
    )


def line_for(structured: StructuredEvent) -> dict[str, Any]:
    stream = io.StringIO()
    emit(structured, stream)
    text = stream.getvalue()
    assert text.endswith("\n") and text.count("\n") == 1  # exactly one line
    parsed: dict[str, Any] = json.loads(text)
    return parsed


def test_one_line_is_keyed_by_session_and_turn() -> None:
    line = line_for(event({"code": "timeout"}))
    assert line == {
        "at": "2026-10-21T12:30:00+00:00",
        "severity": "WARNING",
        "session_id": "s1",
        "turn_id": "t1",
        "event": "turn_failed",
        "code": "timeout",
    }


def test_an_event_outside_a_turn_has_null_keys() -> None:
    structured = StructuredEvent(
        at=NOW, severity="INFO", session_id=None, turn_id=None, event="answer_cut", payload={}
    )
    line = line_for(structured)
    assert line["session_id"] is None and line["turn_id"] is None


def test_free_text_in_the_payload_is_redacted() -> None:
    line = line_for(event({"detail": "falló con lucia@example.com y el 612 345 678"}))
    assert line["detail"] == "falló con [email] y el [phone]"


def test_nested_free_text_is_redacted_too() -> None:
    line = line_for(event({"error": {"messages": ["escribe a ana@example.com"]}}))
    assert line["error"] == {"messages": ["escribe a [email]"]}


def test_numbers_and_flags_pass_through() -> None:
    line = line_for(event({"attempt": 2, "first_output_ms": 840, "retried": True}))
    assert (line["attempt"], line["first_output_ms"], line["retried"]) == (2, 840, True)


def test_the_envelope_cannot_be_overwritten_by_the_payload() -> None:
    line = line_for(event({"event": "forged", "session_id": "other", "severity": "INFO"}))
    assert (line["event"], line["session_id"], line["severity"]) == ("turn_failed", "s1", "WARNING")


@pytest.mark.parametrize("key", ["text", "transcript", "content", "message"])
def test_a_payload_that_looks_like_a_transcript_is_refused(key: str) -> None:
    with pytest.raises(ValueError, match="transcript"):
        emit(event({key: "Me llamo Lucía"}), io.StringIO())


def test_emit_writes_to_stdout_by_default(capsys: pytest.CaptureFixture[str]) -> None:
    emit(event({"code": "timeout"}))
    assert json.loads(capsys.readouterr().out)["code"] == "timeout"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("mi correo es lucia.marin@example.com.", "mi correo es [email]."),
        ("llámame al 612345678", "llámame al [phone]"),
        ("o al +34 612 345 678", "o al [phone]"),
        ("fijo 91 234 56 78", "fijo [phone]"),
        ("DNI 12345678Z", "DNI [id]"),
        ("NIE X1234567L", "NIE [id]"),
        ("IBAN ES91 2100 0418 4502 0005 1332", "IBAN [iban]"),
        ("tarjeta 4111 1111 1111 1111", "tarjeta [card]"),
        ("tarjeta 4111-1111-1111-1111.", "tarjeta [card]."),
        ("4111111111111111", "[card]"),
        ("clave pk-lf-1234567890abcdef", "clave [secret]"),
        ("Authorization: Bearer abc.def-123", "Authorization: [secret]"),
        ("api_key=hunter2hunter2", "[secret]"),
    ],
)
def test_redact_masks_personal_data_and_secrets(raw: str, expected: str) -> None:
    assert redact(raw) == expected


def test_redact_leaves_ordinary_text_and_small_numbers_alone() -> None:
    text = "Abrimos de 8 a 15 h, 3 días, calle Mayor 12"
    assert redact(text) == text


@pytest.mark.parametrize(
    "text",
    [
        '{"slot_id": "chamberi_barista_v1-2026-10-21-1030"}',  # the id must stay legible
        "el 2026-10-21 a las 10:30",
    ],
)
def test_redact_leaves_slot_ids_and_dates_alone(text: str) -> None:
    assert redact(text) == text


def test_redact_truncates_after_masking_so_a_cut_never_leaves_half_an_email() -> None:
    raw = "x" * 10 + " lucia@example.com " + "y" * 50
    result = redact(raw, limit=20)
    assert len(result) == 20 and result.endswith("…")
    assert "@" not in result and "lucia" not in result
