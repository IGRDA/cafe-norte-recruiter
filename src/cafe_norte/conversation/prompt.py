"""Prompt assembly: the versioned system prompt plus the facts of this session, as data."""

import json
import re
from datetime import date, timedelta

from pydantic import BaseModel, ConfigDict

from cafe_norte.conversation import prompts
from cafe_norte.conversation.brief import slot_time
from cafe_norte.conversation.signals import Control
from cafe_norte.domain.candidate import VALUE_FIELDS, unfinished_fields
from cafe_norte.domain.contracts import (
    CandidateRecord,
    Sentiment,
    SessionState,
    StoreConfiguration,
)
from cafe_norte.domain.fields import value_of
from cafe_norte.model.contracts import ModelMessage
from cafe_norte.persistence.contracts import TurnRecord

HISTORY_TURNS = 20

# A sentence ends at . ! ? … (optionally followed by a closing bracket) when whitespace, an
# opening mark, or a capital letter follows. "3.5" stays whole; "?Sí" splits.
_SENTENCE_END = re.compile(r"(?:(?<=[.!?…])|(?<=[.!?…][)\]]))(?:\s+|(?=[¿¡(A-ZÁÉÍÓÚÑÜ]))")


class PromptHints(BaseModel):
    """What this turn adds beyond the stored state: the explicit requests detected in its text
    and the sentiment of the previous turn, when fresh (``signals.fresh_sentiment``)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    explicit: frozenset[Control] = frozenset()
    sentiment: Sentiment | None = None
    readback_answered: str | None = None  # the runtime resolved a plain yes/no this turn
    slot_choice: str | None = None  # the runtime matched the candidate's slot choice (D41)


WEEKDAYS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")


def system_message(
    configuration: StoreConfiguration, state: SessionState, today: date, hints: PromptHints
) -> ModelMessage:
    facts = {
        "today": {"date": today.isoformat(), "weekday": WEEKDAYS[today.weekday()]},
        "next_days": {
            WEEKDAYS[(today + timedelta(days=n)).weekday()]: (today + timedelta(days=n)).isoformat()
            for n in range(1, 7)
        },
        "store": {
            "name": configuration.store_name,
            "city": configuration.city,
            "hours_per_week": configuration.hours_per_week,
            "shifts": [
                {
                    "id": s.shift_id,
                    "label": s.label[state.language],
                    "hours": f"{s.starts}-{s.ends}",
                }
                for s in configuration.shifts
            ],
        },
        "language": state.language,
        "candidate_known_values": known_values(state.candidate),
        "candidate_field_status": field_status(state.candidate),
        "fields_still_to_ask": list(unfinished_fields(state.candidate)),
        "pending_confirmation": pending_facts(state),
        "schedule_intent": state.schedule_intent is not None,
        "booking": booking_facts(state, configuration),
        "lifecycle": state.lifecycle,
        "explicit_requests": sorted(c for c in hints.explicit if c in ("stop", "human")),
        "candidate_sentiment": hints.sentiment,
        "readback_answered": hints.readback_answered,
        "slot_choice": hints.slot_choice,
    }
    content = (
        prompts.load("system")
        + "\n\n## Datos de esta sesión (JSON)\n"
        + json.dumps(facts, ensure_ascii=False, default=str)
        + "\n\n"
        + prompts.load("language", state.language).strip()  # last, where it weighs most
    )
    return ModelMessage(role="system", content=content)


def known_values(candidate: CandidateRecord) -> dict[str, object]:
    """Plain values of captured or confirmed fields, in the same shape a patch uses, so the
    model never sees a field rendered as an object it might copy into ``patch``."""
    values: dict[str, object] = {}
    for name in VALUE_FIELDS:
        value = value_of(getattr(candidate, name))
        if value is not None:
            values[name] = sorted(value) if isinstance(value, frozenset) else value
    return values


def pending_facts(state: SessionState) -> dict[str, object] | None:
    """What a bare yes or no would answer, if anything."""
    pending = state.pending_confirmation
    if pending is None:
        return None
    facts: dict[str, object] = {"kind": pending.target.kind, "status": pending.status}
    if pending.target.kind == "field":
        facts["field"] = pending.target.field
    elif pending.target.kind == "slot":
        facts["slot_id"] = pending.target.slot_id
    return facts


def booking_facts(state: SessionState, configuration: StoreConfiguration) -> dict[str, str] | None:
    """The committed simulated reservation, in the store's local time."""
    booking = state.booking
    if booking is None:
        return None
    return {
        "slot_id": booking.slot_id,
        "when": slot_time(booking.starts_at_utc, configuration, state.language),
        "simulated": "yes",
    }


def field_status(candidate: CandidateRecord) -> dict[str, str]:
    return {name: str(getattr(candidate, name).status) for name in VALUE_FIELDS}


def history_messages(turns: tuple[TurnRecord, ...]) -> tuple[ModelMessage, ...]:
    return tuple(
        ModelMessage(role=turn.role, content=turn.text) for turn in turns if turn.text.strip()
    )


def build_messages(
    configuration: StoreConfiguration,
    state: SessionState,
    history: tuple[TurnRecord, ...],
    user_text: str,
    today: date,
    hints: PromptHints,
) -> tuple[ModelMessage, ...]:
    return (
        system_message(configuration, state, today, hints),
        *history_messages(history),
        ModelMessage(role="user", content=user_text),
    )


_DOT_RUN = re.compile(r"(?:\.\s*){3,}$")
_STAGE_DIRECTION = re.compile(r"^[(\[].*[)\]]$", re.DOTALL)


def split_sentences(buffer: str) -> tuple[list[str], str]:
    """Complete sentences in ``buffer`` and the unfinished remainder. Sentences that are only
    a stage direction in brackets are dropped; a trailing run of dots is trimmed."""
    parts = _SENTENCE_END.split(buffer)
    if len(parts) <= 1:
        return [], buffer
    complete = [s for s in (clean_sentence(p) for p in parts[:-1]) if s]
    return complete, parts[-1]


def clean_sentence(text: str) -> str:
    """What is safe to say aloud from one sentence; empty when nothing is."""
    sentence = _DOT_RUN.sub(".", text.strip()).strip()  # "Vale........" -> "Vale."
    if not sentence or _STAGE_DIRECTION.match(sentence):
        return ""
    return sentence
