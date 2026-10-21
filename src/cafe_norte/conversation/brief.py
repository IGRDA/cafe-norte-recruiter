"""The deterministic brief and the one-line read-backs: record in, exact sentences out.

Sentences live in ``prompts/brief.md``; this module only fills them. What it returns is the
text the runtime speaks and the text a confirmation stores, so it is never paraphrased."""

from collections.abc import Callable
from datetime import date
from functools import cache
from typing import Any, Literal

from cafe_norte.conversation import prompts
from cafe_norte.domain.contracts import (
    CandidateFieldName,
    CandidateRecord,
    StoreConfiguration,
    Weekday,
)
from cafe_norte.domain.fields import value_of

WEEKDAY_ORDER: tuple[Weekday, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
ReadbackField = Literal["contact_phone", "earliest_start_date"]


@cache
def _texts() -> dict[str, str]:
    return prompts.table("brief")


def render_brief_es(
    record: CandidateRecord, configuration: StoreConfiguration, *, followup: bool
) -> str:
    """Four to eight short sentences; unknown and declined fields stay visible; the optional
    phone appears only when given; a requested human follow-up is stated; ends with the
    confirmation question."""
    t = _texts()
    parts = [t["intro"]]
    parts += _fact(record, "name", lambda v: t["name"].format(value=v))
    parts += _fact(record, "interest", lambda v: t[f"interest.{v}"])
    parts += _fact(record, "work_authorization", lambda v: t[f"work_authorization.{v}"])
    parts += _availability(record, configuration)
    parts += _fact(
        record, "earliest_start_date", lambda v: t["earliest_start_date"].format(value=_date(v))
    )
    parts += _fact(record, "experience", lambda v: t["experience"].format(value=str(v).rstrip(".")))
    if value_of(record.contact_phone) is not None:
        parts += _fact(
            record, "contact_phone", lambda v: t["contact_phone"].format(value=_phone(v))
        )
    if followup:
        parts.append(t["followup"])
    parts.append(t["question"])
    return " ".join(parts)


def field_readback(field: ReadbackField, value: object, configuration: StoreConfiguration) -> str:
    shown = _phone(str(value)) if field == "contact_phone" else _date(value)
    return _texts()[f"readback.{field}"].format(value=shown)


# ---- pieces ------------------------------------------------------------------------------------


def _fact(
    record: CandidateRecord, name: CandidateFieldName, render: Callable[[Any], str]
) -> list[str]:
    """The sentence for a value, or the unknown/declined sentence; nothing when unset."""
    t = _texts()
    field = getattr(record, name)
    if field.status == "unknown":
        return [t["unknown"].format(label=t[f"label.{name}"])]
    if field.status == "declined":
        return [t["declined"].format(label=t[f"label.{name}"])]
    value = value_of(field)
    return [] if value is None else [render(value)]


def _availability(record: CandidateRecord, configuration: StoreConfiguration) -> list[str]:
    """One sentence when days, shifts and hours are all known; otherwise one per field, so an
    unknown or declined part stays visible on its own."""
    t = _texts()
    days = value_of(record.availability_days)
    shifts = value_of(record.availability_shifts)
    hours = value_of(record.hours_per_week)
    if days is not None and shifts is not None and hours is not None:
        return [
            t["availability"].format(
                days=_days(days), shifts=_shifts(shifts, configuration), hours=hours
            )
        ]
    return (
        _fact(record, "availability_days", lambda v: t["availability_days"].format(value=_days(v)))
        + _fact(
            record,
            "availability_shifts",
            lambda v: t["availability_shifts"].format(value=_shifts(v, configuration)),
        )
        + _fact(record, "hours_per_week", lambda v: t["hours_per_week"].format(value=v))
    )


def _join(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return f"{', '.join(items[:-1])} {_texts()['and']} {items[-1]}"


def _days(days: frozenset[Weekday]) -> str:
    names = _texts()["weekdays"].split(",")
    return _join([names[WEEKDAY_ORDER.index(d)] for d in WEEKDAY_ORDER if d in days])


def _shifts(shift_ids: frozenset[str], configuration: StoreConfiguration) -> str:
    """Store labels in the store's order; an id the store no longer has is shown as is."""
    labelled = [s.label["es"] for s in configuration.shifts if s.shift_id in shift_ids]
    known = {s.shift_id for s in configuration.shifts}
    return _join(labelled + sorted(shift_ids - known))


def _date(value: object) -> str:
    assert isinstance(value, date)
    t = _texts()
    weekday = t["weekdays"].split(",")[value.weekday()]
    month = t["months"].split(",")[value.month - 1]
    return f"{weekday} {value.day} de {month} de {value.year}"


def _phone(e164: str) -> str:
    """``+34612345678`` → ``+34 612 345 678``; other lengths are grouped in threes from the end."""
    digits = e164.lstrip("+")
    country, rest = (digits[:2], digits[2:]) if len(digits) >= 11 else (digits[:1], digits[1:])
    groups = [rest[max(i - 3, 0) : i] for i in range(len(rest), 0, -3)][::-1]
    return f"+{country} {' '.join(groups)}"
