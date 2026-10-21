"""One candidate turn folded from runtime events: the same reducer serves the fake replay and
the live SSE stream, so both modes score the same thing."""

from evals.contracts import TurnObservation
from evals.observation import fold, observe

from cafe_norte.conversation.contracts import (
    AssistantText,
    SourcesShown,
    ToolFinished,
    ToolStarted,
    TurnFailed,
    TurnFinished,
    TurnStarted,
)
from cafe_norte.domain.contracts import SessionId, TurnId
from cafe_norte.observability.contracts import StageTiming, UsageRecord

TURN = TurnId("t1")
TIMING = StageTiming(
    session_id=SessionId("s"), turn_id=TURN, stage="text_total", milliseconds=900, source="server"
)
USAGE = UsageRecord(
    session_id=SessionId("s"),
    turn_id=TURN,
    kind="llm_tokens",
    unit_detail="gpt-4o-mini:input",
    quantity=1200,
    estimated=False,
)


def test_a_turn_collects_what_was_said_shown_and_called() -> None:
    observation = observe(
        [
            TurnStarted(turn_id=TURN, language="es", text="hola"),
            ToolStarted(name="search_knowledge"),
            ToolFinished(name="search_knowledge", ok=True, summary=""),
            SourcesShown(
                question="q", chunk_ids=("a#1", "b#2"), titles=(), sections=(), excerpts=()
            ),
            AssistantText(text="Uno.", spoken_form="Uno."),
            AssistantText(text="¿Dos?", spoken_form="¿Dos?"),
            TurnFinished(turn_id=TURN, interrupted=False, usage=(USAGE,), timings=(TIMING,)),
        ]
    )
    assert observation == TurnObservation(
        turn_id=TURN,
        spoken=("Uno.", "¿Dos?"),
        sources=("a#1", "b#2"),
        tools=(("search_knowledge", True),),
        usage=(USAGE,),
        timings=(TIMING,),
        done=True,
    )


def test_a_failed_turn_keeps_its_code_and_is_done() -> None:
    observation = observe([TurnFailed(turn_id=TURN, code="timeout", message="m")])
    assert observation.failed == "timeout"
    assert observation.done


def test_the_fold_is_open_until_the_turn_ends() -> None:
    observation = fold(TurnObservation(), AssistantText(text="Hola.", spoken_form="Hola."))
    assert observation.spoken == ("Hola.",)
    assert not observation.done


def test_an_unrelated_event_changes_nothing() -> None:
    start = TurnObservation(spoken=("x",))
    assert fold(start, ToolStarted(name="update_candidate")) == start
