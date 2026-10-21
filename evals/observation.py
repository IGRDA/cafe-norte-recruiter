"""Fold one turn's runtime events into a ``TurnObservation``. The fake replay reads them from
``Runtime.run_turn``, the live runner from the SSE stream; both are the same ``RuntimeEvent``
union, so both modes score the same value."""

from collections.abc import Iterable, Sequence

from cafe_norte.conversation.contracts import (
    AssistantText,
    RuntimeEvent,
    SourcesShown,
    StateUpdated,
    ToolFinished,
    TurnFailed,
    TurnFinished,
    TurnStarted,
)
from cafe_norte.domain.contracts import SessionState, Signal
from cafe_norte.persistence.contracts import TurnRecord
from evals.contracts import SessionResult, TurnObservation


def fold(observation: TurnObservation, event: RuntimeEvent) -> TurnObservation:
    """One event more. Events that say nothing the checks read leave the value unchanged."""
    match event:
        case TurnStarted(turn_id=turn_id):
            return observation.model_copy(update={"turn_id": turn_id})
        case AssistantText(text=text):
            return observation.model_copy(update={"spoken": (*observation.spoken, text)})
        case SourcesShown(chunk_ids=chunk_ids):
            return observation.model_copy(update={"sources": (*observation.sources, *chunk_ids)})
        case ToolFinished(name=name, ok=ok):
            return observation.model_copy(update={"tools": (*observation.tools, (name, ok))})
        case StateUpdated(lifecycle=lifecycle):
            return observation.model_copy(update={"lifecycle": lifecycle})
        case TurnFinished(turn_id=turn_id, usage=usage, timings=timings):
            return observation.model_copy(
                update={"turn_id": turn_id, "usage": usage, "timings": timings, "done": True}
            )
        case TurnFailed(turn_id=turn_id, code=code):
            return observation.model_copy(update={"turn_id": turn_id, "failed": code, "done": True})
        case _:
            return observation


def observe(events: Iterable[RuntimeEvent]) -> TurnObservation:
    observation = TurnObservation()
    for event in events:
        observation = fold(observation, event)
    return observation


def session_result(
    state: SessionState,
    turns: Sequence[TurnRecord],
    observations: Sequence[TurnObservation],
    *,
    allowed_doc_ids: frozenset[str],
    signals: Sequence[Signal] = (),
) -> SessionResult:
    """What the checks read: the final state and transcript, and one observation per
    candidate line, in order."""
    return SessionResult(
        state=state,
        turns=tuple(turns),
        spoken_by_turn=tuple(o.spoken for o in observations),
        sources_by_turn=tuple(o.sources for o in observations),
        allowed_doc_ids=allowed_doc_ids,
        signals=tuple(signals),
        tools_by_turn=tuple(o.tools for o in observations),
        failed_by_turn=tuple(o.failed for o in observations),
    )
