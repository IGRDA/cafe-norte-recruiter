"""The deterministic brief and the one-line read-backs: record in, exact sentences out.

Sentences live in ``prompts/brief.<language>.md``; this module only fills them. What it returns
is the text the runtime speaks and the text a confirmation stores, so it is never paraphrased."""

from collections.abc import Callable
from datetime import date, datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from cafe_norte.conversation import prompts
from cafe_norte.domain.contracts import (
    CandidateFieldName,
    CandidateRecord,
    InterviewSlot,
    StoreConfiguration,
    Weekday,
    YearMonth,
)
from cafe_norte.domain.fields import value_of
from cafe_norte.errors import Language

WEEKDAY_ORDER: tuple[Weekday, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
ReadbackField = Literal["contact_phone", "earliest_start_date"]


def _texts(language: Language) -> dict[str, str]:
    return prompts.table("brief", language)


def render_brief(
    record: CandidateRecord,
    configuration: StoreConfiguration,
    language: Language,
    *,
    followup: bool = False,
) -> str:
    """Four to eight short sentences; unknown and declined fields stay visible; the optional
    phone appears only when given; a requested human follow-up is stated; ends with the
    confirmation question."""
    t = _texts(language)
    parts = [t["intro"]]
    parts += _fact(record, "name", t, lambda v: t["name"].format(value=v))
    parts += _fact(record, "interest", t, lambda v: t[f"interest.{v}"])
    parts += _fact(record, "work_authorization", t, lambda v: t[f"work_authorization.{v}"])
    parts += _availability(record, configuration, language)
    parts += _fact(
        record,
        "earliest_start_date",
        t,
        lambda v: t["earliest_start_date"].format(value=_start(v, t)),
    )
    parts += _fact(
        record, "experience", t, lambda v: t["experience"].format(value=str(v).rstrip("."))
    )
    if value_of(record.contact_phone) is not None:
        parts += _fact(
            record, "contact_phone", t, lambda v: t["contact_phone"].format(value=_phone(v))
        )
    if followup:
        parts.append(t["followup"])
    parts.append(t["question"])
    return " ".join(parts)


def render_brief_changes(
    record: CandidateRecord,
    configuration: StoreConfiguration,
    language: Language,
    *,
    since: str,
) -> str | None:
    """The brief's sentences that are not in ``since`` (the brief as it was last read back),
    with the closing question: what a correction changed, said once instead of the whole
    brief again (D59). ``None`` when nothing or everything changed."""
    from cafe_norte.conversation.prompt import sentences  # prompt imports this module

    t = _texts(language)
    now = sentences(render_brief(record, configuration, language))
    before = set(sentences(since))
    facts = [s for s in now if s not in (t["intro"], t["question"])]
    changed = [s for s in facts if s not in before]
    if not changed or len(changed) == len(facts):
        return None
    return " ".join([*changed, t["question"]])


def field_readback(field: ReadbackField, value: object, language: Language) -> str:
    t = _texts(language)
    shown = _phone(str(value)) if field == "contact_phone" else _start(value, t)
    return t[f"readback.{field}"].format(value=shown)


def slot_readback(
    slot: InterviewSlot, configuration: StoreConfiguration, language: Language
) -> str:
    return _texts(language)["readback.slot"].format(
        store=configuration.store_name,
        value=slot_time(slot.starts_at_utc, configuration, language),
    )


def review_check(language: Language) -> str:
    """The short check said after each part of a read-back that is gone over (D39)."""
    return _texts(language)["review.check"]


def brief_intro(language: Language) -> str:
    return _texts(language)["intro"]


def slot_time(
    starts_at_utc: datetime, configuration: StoreConfiguration, language: Language
) -> str:
    """``jueves 22 de octubre de 2026 a las 10:30`` in the store's timezone, in the session
    language."""
    t = _texts(language)
    local = starts_at_utc.astimezone(ZoneInfo(configuration.timezone))
    return t["slot_time"].format(date=_date(local.date(), t), time=local.strftime("%H:%M"))


# ---- pieces ------------------------------------------------------------------------------------


def _fact(
    record: CandidateRecord,
    name: CandidateFieldName,
    t: dict[str, str],
    render: Callable[[Any], str],
) -> list[str]:
    """The sentence for a value, or the unknown/declined sentence; nothing when unset."""
    field = getattr(record, name)
    if field.status == "unknown":
        return [t["unknown"].format(label=t[f"label.{name}"])]
    if field.status == "declined":
        return [t["declined"].format(label=t[f"label.{name}"])]
    value = value_of(field)
    return [] if value is None else [render(value)]


def _availability(
    record: CandidateRecord, configuration: StoreConfiguration, language: Language
) -> list[str]:
    """One sentence when days, shifts and hours are all known; otherwise one per field, so an
    unknown or declined part stays visible on its own."""
    t = _texts(language)
    days = value_of(record.availability_days)
    shifts = value_of(record.availability_shifts)
    hours = value_of(record.hours_per_week)
    if days is not None and shifts is not None and hours is not None:
        return [
            t["availability"].format(
                days=_days(days, t),
                shifts=_shifts(shifts, configuration, language),
                hours=hours,
            )
        ]
    return (
        _fact(
            record,
            "availability_days",
            t,
            lambda v: t["availability_days"].format(value=_days(v, t)),
        )
        + _fact(
            record,
            "availability_shifts",
            t,
            lambda v: t["availability_shifts"].format(value=_shifts(v, configuration, language)),
        )
        + _fact(record, "hours_per_week", t, lambda v: t["hours_per_week"].format(value=v))
    )


def _join(items: list[str], t: dict[str, str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return f"{', '.join(items[:-1])} {t['and']} {items[-1]}"


def _days(days: frozenset[Weekday], t: dict[str, str]) -> str:
    names = t["weekdays"].split(",")
    return _join([names[WEEKDAY_ORDER.index(d)] for d in WEEKDAY_ORDER if d in days], t)


def _shifts(
    shift_ids: frozenset[str], configuration: StoreConfiguration, language: Language
) -> str:
    """Store labels in the store's order; an id the store no longer has is shown as is."""
    labelled = [s.label_in(language) for s in configuration.shifts if s.shift_id in shift_ids]
    known = {s.shift_id for s in configuration.shifts}
    return _join(labelled + sorted(shift_ids - known), _texts(language))


def _date(value: object, t: dict[str, str]) -> str:
    assert isinstance(value, date)
    weekday = t["weekdays"].split(",")[value.weekday()]
    month = t["months"].split(",")[value.month - 1]
    return t["date"].format(weekday=weekday, day=value.day, month=month, year=value.year)


def _start(value: object, t: dict[str, str]) -> str:
    """A start date with its preposition ("el lunes 2 de noviembre de 2026"), or the month alone
    ("en enero de 2027") when that is all the candidate said (D58)."""
    if isinstance(value, YearMonth):
        month = t["months"].split(",")[value.month - 1]
        return t["start.in"].format(month=month, year=value.year)
    return t["start.on"].format(value=_date(value, t))


def _phone(e164: str) -> str:
    """``+34612345678`` → ``+34 612 345 678``; other lengths are grouped in threes from the end."""
    digits = e164.lstrip("+")
    country, rest = (digits[:2], digits[2:]) if len(digits) >= 11 else (digits[:1], digits[1:])
    groups = [rest[max(i - 3, 0) : i] for i in range(len(rest), 0, -3)][::-1]
    return f"+{country} {' '.join(groups)}"
