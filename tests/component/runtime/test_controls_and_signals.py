"""Explicit controls and the opt-in signal analyzers, as the runtime applies them."""

import asyncio
import json

from cafe_norte.conversation import prompts
from cafe_norte.conversation.contracts import (
    AssistantText,
    RuntimeEvent,
    SignalAnalysis,
    SignalRecorded,
    StateUpdated,
    TurnFinished,
    TurnStarted,
)
from cafe_norte.conversation.runtime import Limits
from cafe_norte.conversation.signals import DecisionSignalAnalyzer, ModelSignalAnalyzer
from cafe_norte.domain.contracts import (
    Signal,
    TurnId,
)
from cafe_norte.errors import Language
from cafe_norte.model.contracts import (
    ModelMessage,
    ToolCall,
)
from cafe_norte.model.fake import FakeDecisionModel, FakeModel
from tests.support.builders import SESSION
from tests.support.harness import (
    WANTS_TOOLS,
    Harness,
    decision_analyzer,
    says,
    turn,
)


def session_facts(messages: tuple[ModelMessage, ...]) -> dict[str, object]:
    """The JSON facts of the system message; the language line follows them."""
    facts, _ = json.JSONDecoder().raw_decode(messages[0].content.split("(JSON)\n", 1)[1])
    assert isinstance(facts, dict)
    return facts


def verdicts(*sentiments: str) -> ModelSignalAnalyzer:
    """A classifier that answers one verdict per turn; the evidence is the word "lento"."""
    replies = [
        json.dumps({"sentiment": s, "evidence_text": "" if s == "neutral" else "lento"})
        for s in sentiments
    ]
    return ModelSignalAnalyzer(FakeModel([says(r) for r in replies]))


async def test_a_human_request_is_saved_then_answered_with_the_fixed_reply() -> None:
    h = Harness([says("Claro, te paso. ¿Algo más?")])
    await h.open_session()
    events: list[RuntimeEvent] = []
    async for event in h.runtime.run_turn(turn("Quiero hablar con una persona.")):
        if isinstance(event, AssistantText) and not any(
            isinstance(e, AssistantText) for e in events
        ):
            state = await h.store.sessions.get(SESSION)
            assert state is not None and [f.kind for f in state.review_flags] == ["human_followup"]
        events.append(event)
    reply = prompts.table("controls", "es")["human"]
    assert " ".join(e.text for e in events if isinstance(e, AssistantText)) == reply
    assert any(isinstance(e, StateUpdated) for e in events)
    assert session_facts(h.model.calls[0])["explicit_requests"] == ["human"]


async def test_the_models_own_follow_up_call_in_that_turn_adds_no_second_flag() -> None:
    call = ToolCall(
        call_id="c1",
        name="request_human_followup",
        arguments_json=json.dumps({"reason": "quiere hablar con una persona"}),
    )
    h = Harness([[call, WANTS_TOOLS], says("")])
    await h.open_session()
    await h.run("Quiero hablar con una persona.")
    state = await h.store.sessions.get(SESSION)
    assert state is not None and len(state.review_flags) == 1


async def test_a_stop_request_is_a_hint_for_the_model_not_a_runtime_ending() -> None:
    h = Harness([says("Vale.")])
    await h.open_session()
    await h.run("Quiero parar.")
    assert session_facts(h.model.calls[0])["explicit_requests"] == ["stop"]
    state = await h.store.sessions.get(SESSION)
    assert state is not None and state.lifecycle == "active"


async def test_a_frustrated_turn_shapes_the_next_prompt_only() -> None:
    h = Harness(
        [says("Uno."), says("Dos."), says("Tres.")],
        signals=verdicts("frustrated", "neutral", "neutral"),
    )
    await h.open_session()
    for index, text in enumerate(["Esto va lento.", "Me llamo Ane.", "Vale."], start=1):
        await h.run(text, f"in-{index}")
        await h.runtime.settle()
    sentiments = [session_facts(call)["candidate_sentiment"] for call in h.model.calls]
    assert sentiments == [None, "frustrated", None]


async def test_a_verdict_is_journaled_against_its_source_turn() -> None:
    h = Harness([says("Uno.")], signals=verdicts("frustrated"))
    await h.open_session()
    events = await h.run("Esto va lento.")
    await h.runtime.settle()
    source = next(e.turn_id for e in events if isinstance(e, TurnStarted))
    recorded = [
        SignalRecorded.model_validate_json(e.payload_json).signal
        for e in await h.journal()
        if e.kind == "signal_recorded"
    ]
    assert [(s.turn_id, s.sentiment, s.evidence_text) for s in recorded] == [
        (source, "frustrated", "lento")
    ]


async def test_a_verdict_that_arrives_after_the_next_turn_started_is_not_used() -> None:
    class Gated:
        switches_language = False

        """Turn 1's verdict waits until the test lets it through; later ones are immediate."""

        def __init__(self) -> None:
            self.release = asyncio.Event()
            self.calls = 0

        async def analyze(
            self, turn_id: TurnId, text: str, language: Language, *, ana_said: str = ""
        ) -> SignalAnalysis:
            self.calls += 1
            if self.calls == 1:
                await self.release.wait()
            signal = Signal(
                turn_id=turn_id,
                sentiment="frustrated",
                explicit_human_request=False,
                explicit_stop=False,
                language_switch_to=None,
                evidence_text="",
            )
            return SignalAnalysis(signal=signal, usage=None, model_id="slow")

    gated = Gated()
    h = Harness([says("Uno."), says("Dos."), says("Tres.")], signals=gated)
    await h.open_session()
    await h.run("Esto va lento.", "in-1")
    await h.run("Me llamo Ane.", "in-2")  # turn 1's verdict is not in yet
    gated.release.set()
    await h.runtime.settle()
    await h.run("Vale.", "in-3")  # turn 2's verdict is fresh
    sentiments = [session_facts(call)["candidate_sentiment"] for call in h.model.calls]
    assert sentiments == [None, None, "frustrated"]


async def test_a_failing_analyzer_never_reaches_the_turn() -> None:
    class Broken:
        switches_language = False

        async def analyze(
            self, turn_id: TurnId, text: str, language: Language, *, ana_said: str = ""
        ) -> SignalAnalysis:
            raise RuntimeError("boom")

    h = Harness([says("Uno."), says("Dos.")], signals=Broken())
    await h.open_session()
    first = await h.run("Hola.", "in-1")
    await h.runtime.settle()
    second = await h.run("Hola otra vez.", "in-2")
    assert isinstance(first[-1], TurnFinished) and isinstance(second[-1], TurnFinished)
    assert not any(e.kind == "signal_recorded" for e in await h.journal())


# ---- a switch the decision-model analyzer read ---------------------------------------------


async def test_a_switch_the_analyzer_read_applies_at_the_start_of_the_next_turn() -> None:
    h = Harness([says("Vale."), says("Great.")], signals=decision_analyzer(0.95, 0.0))
    await h.open_session()
    await h.run("Sorry, my Spanish is not very good.", "in-1")
    await h.runtime.settle()
    events = await h.run("Monday to Friday.", "in-2")
    started = next(e for e in events if isinstance(e, TurnStarted))
    assert started.language == "en"
    state = await h.store.sessions.get(SESSION)
    assert state is not None and state.language == "en"
    turns = await h.store.turns.recent(SESSION, 10)
    assert [t.language for t in turns if t.role == "user"] == ["es", "en"]


async def test_a_switch_below_the_threshold_or_too_late_changes_nothing() -> None:
    h = Harness([says("Uno."), says("Dos.")], signals=decision_analyzer(0.6))
    await h.open_session()
    await h.run("Mi español es regular.", "in-1")
    await h.runtime.settle()
    events = await h.run("Vale.", "in-2")
    assert next(e for e in events if isinstance(e, TurnStarted)).language == "es"

    late = Harness(
        [says("Uno."), says("Dos.")],
        signals=decision_analyzer(0.95, delay=0.05),
        limits=Limits(switch_wait_seconds=0),  # only the next-turn path
    )
    await late.open_session()
    await late.run("Sorry, my Spanish is not very good.", "in-1")
    events = await late.run("Okay.", "in-2")  # no verdict yet: the session language stays
    assert next(e for e in events if isinstance(e, TurnStarted)).language == "es"


async def test_an_explicit_request_this_turn_wins_over_the_previous_verdict() -> None:
    h = Harness([says("Vale."), says("Perfecto.")], signals=decision_analyzer(0.95, 0.0))
    await h.open_session()
    await h.run("Sorry, my Spanish is not very good.", "in-1")
    await h.runtime.settle()
    events = await h.run("No, mejor en español, por favor.", "in-2")
    assert next(e for e in events if isinstance(e, TurnStarted)).language == "es"


async def test_the_analyzer_reads_what_ana_said_before_the_message() -> None:
    model = FakeDecisionModel([])
    h = Harness(
        [says("¿Qué días puedes trabajar?"), says("Vale.")], signals=DecisionSignalAnalyzer(model)
    )
    await h.open_session()
    await h.run("Me llamo Ane.", "in-1")
    await h.runtime.settle()
    await h.run("Monday to Friday.", "in-2")
    await h.runtime.settle()
    assert [s["ana_said"] for s in model.states][1] == "¿Qué días puedes trabajar?"
    assert model.states[1]["candidate_said"] == "Monday to Friday."
