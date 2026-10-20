"""Prompt assembly: the versioned system prompt plus the facts of this session, as data."""

import json
import re

from cafe_norte.conversation import prompts
from cafe_norte.domain.candidate import unfinished_fields
from cafe_norte.domain.contracts import CandidateRecord, SessionState, StoreConfiguration
from cafe_norte.domain.fields import value_of
from cafe_norte.model.contracts import ModelMessage
from cafe_norte.persistence.contracts import TurnRecord

HISTORY_TURNS = 20

_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")


def system_message(configuration: StoreConfiguration, state: SessionState) -> ModelMessage:
    facts = {
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
        "candidate": candidate_facts(state.candidate),
        "fields_still_to_ask": list(unfinished_fields(state.candidate)),
    }
    content = (
        prompts.load("system")
        + "\n\n## Datos de esta sesión (JSON)\n"
        + json.dumps(facts, ensure_ascii=False, default=str)
    )
    return ModelMessage(role="system", content=content)


def candidate_facts(candidate: CandidateRecord) -> dict[str, dict[str, object]]:
    """Status and value per field; values only when captured or confirmed."""
    facts: dict[str, dict[str, object]] = {}
    for name in type(candidate).model_fields:
        field = getattr(candidate, name)
        if hasattr(field, "status"):
            facts[name] = {"status": field.status}
            value = value_of(field)
            if value is not None:
                facts[name]["value"] = sorted(value) if isinstance(value, frozenset) else value
    return facts


def history_messages(turns: tuple[TurnRecord, ...]) -> tuple[ModelMessage, ...]:
    return tuple(
        ModelMessage(role=turn.role, content=turn.text) for turn in turns if turn.text.strip()
    )


def build_messages(
    configuration: StoreConfiguration,
    state: SessionState,
    history: tuple[TurnRecord, ...],
    user_text: str,
) -> tuple[ModelMessage, ...]:
    return (
        system_message(configuration, state),
        *history_messages(history),
        ModelMessage(role="user", content=user_text),
    )


def split_sentences(buffer: str) -> tuple[list[str], str]:
    """Complete sentences in ``buffer`` and the unfinished remainder."""
    parts = _SENTENCE_END.split(buffer)
    if len(parts) <= 1:
        return [], buffer
    complete = [p.strip() for p in parts[:-1] if p.strip()]
    return complete, parts[-1]
