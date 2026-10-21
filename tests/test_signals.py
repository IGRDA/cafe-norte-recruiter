"""Explicit controls (pure patterns), the classifier adapter and signal freshness."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from cafe_norte.conversation.signals import (
    Control,
    ModelSignalAnalyzer,
    explicit_controls,
    fresh_sentiment,
)
from cafe_norte.domain.contracts import Sentiment, Signal, TurnId
from cafe_norte.errors import Language
from cafe_norte.model.contracts import ModelEvent, ModelFinished, ModelText
from cafe_norte.model.fake import FakeModel

HUMAN: frozenset[Control] = frozenset({"human"})
STOP: frozenset[Control] = frozenset({"stop"})
NONE: frozenset[Control] = frozenset()


@pytest.mark.parametrize(
    ("language", "text", "expected"),
    [
        ("es", "Quiero hablar con una persona.", HUMAN),
        ("es", "¿Me pasas con alguien real?", HUMAN),
        ("es", "PREFIERO UN HUMANO", HUMAN),
        ("es", "No, quiero hablar con una persona", HUMAN),  # "no" answers Ana, then a request
        ("es", "no quiero hablar con una persona", NONE),
        ("es", "Una persona del equipo me dijo que viniera.", NONE),
        ("es", "Para.", STOP),
        ("es", "Quiero parar, gracias.", STOP),
        ("es", "Vale, lo dejo aquí.", STOP),
        ("es", "No quiero seguir.", STOP),
        ("es", "Para el turno de mañana me viene bien.", NONE),  # "para", the preposition
        ("es", "No quiero parar, sigamos.", NONE),
        ("es", "Uf, esto es muy lento y no me entero.", NONE),  # tone is the classifier's job
        ("es", "Quiero hablar con una persona. Bueno, mejor lo dejo aquí.", HUMAN | STOP),
        ("en", "I want to talk to a real person", HUMAN),
        ("en", "Can I speak with someone?", HUMAN),
        ("en", "I don't want to talk to a person", NONE),
        ("en", "Stop.", STOP),
        ("en", "I'd like to stop here.", STOP),
        ("en", "I'll stop by the store tomorrow.", NONE),
    ],
)
def test_explicit_controls_examples(
    language: Language, text: str, expected: frozenset[Control]
) -> None:
    assert explicit_controls(text, language) == expected


@given(st.text(), st.sampled_from(["es", "en"]))
def test_explicit_controls_is_total(text: str, language: Language) -> None:
    assert explicit_controls(text, language) <= {"stop", "human"}


REQUESTS = ["quiero hablar con una persona", "pásame con alguien real", "quiero terminar"]


@given(st.sampled_from(REQUESTS), st.lists(st.booleans(), min_size=40, max_size=40))
def test_case_and_accents_do_not_change_the_result(request: str, upper: list[bool]) -> None:
    shouted = "".join(c.upper() if u else c for c, u in zip(request, upper, strict=False))
    plain = request.replace("á", "a")
    assert explicit_controls(shouted, "es") == explicit_controls(request, "es")
    assert explicit_controls(plain, "es") == explicit_controls(request, "es") != NONE


FILLER = st.sampled_from(["", "Vale.", "Mira,", "Pues nada.", "Oye, una cosa:"])


@given(FILLER, st.sampled_from(REQUESTS), FILLER)
def test_a_request_survives_surrounding_clauses(before: str, request: str, after: str) -> None:
    assert explicit_controls(f"{before} {request}. {after}", "es") == explicit_controls(
        request, "es"
    )


# ---- the classifier adapter ----------------------------------------------------------------------


def analyzer(*replies: str, delay: float = 0) -> ModelSignalAnalyzer:
    scripts: list[list[ModelEvent]] = [
        [ModelText(text=r), ModelFinished(reason="stop")] for r in replies
    ]
    return ModelSignalAnalyzer(FakeModel(scripts, delay_seconds=delay), deadline_seconds=0.05)


TEXT = "Uf, esto es muy lento. Quiero hablar con una persona."


async def test_a_backed_verdict_becomes_a_signal_with_the_explicit_flags() -> None:
    reply = '```json\n{"sentiment": "frustrated", "evidence_text": "esto es muy lento"}\n```'
    signal = await analyzer(reply).analyze(TurnId("t1"), TEXT, "es")
    assert signal == Signal(
        turn_id=TurnId("t1"),
        sentiment="frustrated",
        explicit_human_request=True,
        explicit_stop=False,
        language_switch_to=None,
        evidence_text="esto es muy lento",
    )


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
    assert await analyzer(reply).analyze(TurnId("t1"), TEXT, "es") is None


async def test_a_late_verdict_is_no_signal() -> None:
    late = analyzer('{"sentiment": "neutral"}', delay=1)
    assert await late.analyze(TurnId("t1"), TEXT, "es") is None


async def test_a_failing_model_is_no_signal() -> None:
    assert await analyzer().analyze(TurnId("t1"), TEXT, "es") is None  # scripts exhausted


# ---- freshness -----------------------------------------------------------------------------------


def signal(turn: str, sentiment: Sentiment) -> Signal:
    return Signal(
        turn_id=TurnId(turn),
        sentiment=sentiment,
        explicit_human_request=False,
        explicit_stop=False,
        language_switch_to=None,
        evidence_text="",
    )


def test_only_the_previous_turns_soft_sentiment_reaches_the_next_prompt() -> None:
    assert fresh_sentiment(signal("t1", "frustrated"), TurnId("t1")) == "frustrated"
    assert fresh_sentiment(signal("t1", "uncertain"), TurnId("t1")) == "uncertain"
    assert fresh_sentiment(signal("t1", "frustrated"), TurnId("t2")) is None  # stale
    assert fresh_sentiment(signal("t1", "neutral"), TurnId("t1")) is None
    assert fresh_sentiment(signal("t1", "positive"), TurnId("t1")) is None
    assert fresh_sentiment(None, TurnId("t1")) is None
