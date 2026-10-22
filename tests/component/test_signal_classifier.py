"""The opt-in signal classifier: a backed verdict is a signal, anything else is none."""

import pytest

from cafe_norte.conversation.signals import ModelSignalAnalyzer
from cafe_norte.domain.contracts import Signal, TurnId
from cafe_norte.model.contracts import ModelEvent, ModelFinished, ModelText, ModelUsage
from cafe_norte.model.fake import FakeModel


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
