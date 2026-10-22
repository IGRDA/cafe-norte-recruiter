"""The opt-in signal analyzers: a backed verdict is a signal, anything else is none; a decision
model's answers count above their thresholds (D52)."""

import pytest

from cafe_norte.conversation.contracts import SignalAnalysis
from cafe_norte.conversation.signals import DecisionSignalAnalyzer, ModelSignalAnalyzer
from cafe_norte.domain.contracts import Signal, TurnId
from cafe_norte.errors import Language
from cafe_norte.model.contracts import (
    ChoiceAnswer,
    Decision,
    ModelError,
    ModelEvent,
    ModelFinished,
    ModelText,
    ModelUsage,
)
from cafe_norte.model.fake import FakeDecisionModel, FakeModel


def analyzer(*replies: str, delay: float = 0) -> ModelSignalAnalyzer:
    scripts: list[list[ModelEvent]] = [
        [ModelText(text=r), ModelFinished(reason="stop")] for r in replies
    ]
    return ModelSignalAnalyzer(FakeModel(scripts, delay_seconds=delay), deadline_seconds=0.05)


TEXT = "Uf, esto es muy lento. Quiero hablar con una persona."


async def test_a_backed_verdict_becomes_a_signal_with_the_explicit_flags() -> None:
    reply = '```json\n{"sentiment": "frustrated", "evidence_text": "esto es muy lento"}\n```'
    signal = (await analyzer(reply).analyze(TurnId("t1"), TEXT, "es")).signal
    assert signal == Signal(
        turn_id=TurnId("t1"),
        sentiment="frustrated",
        explicit_human_request=True,
        explicit_stop=False,
        language_switch_to=None,
        evidence_text="esto es muy lento",
    )


async def test_a_language_request_is_recorded_on_the_signal() -> None:
    reply = '{"sentiment": "neutral", "evidence_text": ""}'
    signal = (await analyzer(reply).analyze(TurnId("t1"), "In English, please.", "es")).signal
    assert signal is not None and signal.language_switch_to == "en"
    same = (await analyzer(reply).analyze(TurnId("t1"), "In English, please.", "en")).signal
    assert same is not None and same.language_switch_to is None


@pytest.mark.parametrize(
    "reply",
    [
        "not json",
        '{"sentiment": "angry", "evidence_text": "lento"}',  # not a Sentiment
        '{"sentiment": "frustrated", "evidence_text": "odio esto"}',  # words never said
        '{"sentiment": "frustrated", "evidence_text": ""}',  # a tone with no evidence
    ],
)
async def test_an_unbacked_or_malformed_verdict_is_no_signal(reply: str) -> None:
    assert (await analyzer(reply).analyze(TurnId("t1"), TEXT, "es")).signal is None


async def test_a_late_verdict_is_no_signal() -> None:
    late = analyzer('{"sentiment": "neutral"}', delay=1)
    assert (await late.analyze(TurnId("t1"), TEXT, "es")).signal is None


async def test_a_failing_model_is_no_signal() -> None:
    assert (await analyzer().analyze(TurnId("t1"), TEXT, "es")).signal is None  # scripts exhausted


@pytest.mark.parametrize(
    "reply",
    ['{"sentiment": "frustrated", "evidence_text": "esto es muy lento"}', "not json"],
)
async def test_a_verdict_reports_the_tokens_it_cost_whether_or_not_it_is_a_signal(
    reply: str,
) -> None:
    usage = ModelUsage(input_tokens=210, output_tokens=12, model_id="fake-2024-07-18")
    model = FakeModel([[ModelText(text=reply), usage, ModelFinished(reason="stop")]])
    analysis = await ModelSignalAnalyzer(model).analyze(TurnId("t1"), TEXT, "es")
    assert analysis.usage == usage and analysis.model_id == "fake"


# ---- freshness -----------------------------------------------------------------------------------


# ---- the decision-model analyzer (D52) -----------------------------------------------------------


def decision(sentiment: str, p_sentiment: float, p_switch: float) -> Decision:
    rest = {s: 0.0 for s in ("neutral", "positive", "frustrated", "uncertain")}
    return Decision(
        answers={
            "sentiment": ChoiceAnswer(
                choice=sentiment, probabilities=rest | {sentiment: p_sentiment}
            ),
            "language": ChoiceAnswer(
                choice="switch" if p_switch >= 0.5 else "keep",
                probabilities={"keep": 1 - p_switch, "switch": p_switch},
            ),
        },
        model_id="typesafe/jev-1.14-20261014",
        input_tokens=320,
        output_tokens=0,
    )


async def decide(
    reply: Decision | ModelError, text: str = "Sorry, my Spanish is not very good.", **kw: str
) -> tuple[SignalAnalysis, FakeDecisionModel]:
    model = FakeDecisionModel([reply])
    language: Language = "en" if kw.get("language") == "en" else "es"
    analysis = await DecisionSignalAnalyzer(model).analyze(
        TurnId("t1"), text, language, ana_said=kw.get("ana_said", "")
    )
    return analysis, model


async def test_a_switch_above_the_threshold_is_suggested_with_the_message_as_evidence() -> None:
    analysis, model = await decide(decision("uncertain", 0.8, 0.92), ana_said="¿Tu nombre?")
    assert analysis.signal is not None
    assert analysis.signal.language_switch_to == "en"
    assert analysis.signal.sentiment == "uncertain"
    assert analysis.signal.evidence_text == "Sorry, my Spanish is not very good."
    assert model.states == [
        {
            "session_language": "es",
            "ana_said": "¿Tu nombre?",
            "candidate_said": "Sorry, my Spanish is not very good.",
        }
    ]
    assert analysis.usage is not None and analysis.usage.input_tokens == 320


async def test_below_the_thresholds_nothing_is_suggested() -> None:
    analysis, _ = await decide(decision("frustrated", 0.45, 0.6), text="Vale.")
    assert analysis.signal is not None
    assert (analysis.signal.sentiment, analysis.signal.language_switch_to) == ("neutral", None)
    assert analysis.signal.evidence_text == ""


async def test_an_explicit_request_wins_over_the_decision() -> None:
    analysis, _ = await decide(decision("neutral", 1.0, 0.0), text="In English, please.")
    assert analysis.signal is not None and analysis.signal.language_switch_to == "en"


async def test_a_failed_decision_is_no_signal() -> None:
    analysis, _ = await decide(ModelError("HTTP 503", code="provider_unavailable"))
    assert (analysis.signal, analysis.usage) == (None, None)
