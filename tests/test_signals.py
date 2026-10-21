"""Explicit controls (pure patterns: stop, human and language requests), the classifier adapter
and signal freshness."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from cafe_norte.conversation.signals import (
    Control,
    ModelSignalAnalyzer,
    answer_to_readback,
    explicit_controls,
    fresh_sentiment,
    requested_language,
)
from cafe_norte.domain.contracts import Sentiment, Signal, TurnId
from cafe_norte.errors import Language
from cafe_norte.model.contracts import ModelEvent, ModelFinished, ModelText
from cafe_norte.model.fake import FakeModel

HUMAN: frozenset[Control] = frozenset({"human"})
STOP: frozenset[Control] = frozenset({"stop"})
NONE: frozenset[Control] = frozenset()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Quiero hablar con una persona.", HUMAN),
        ("¿Me pasas con alguien real?", HUMAN),
        ("PREFIERO UN HUMANO", HUMAN),
        ("No, quiero hablar con una persona", HUMAN),  # "no" answers Ana, then a request
        ("no quiero hablar con una persona", NONE),
        ("Una persona del equipo me dijo que viniera.", NONE),
        ("Para.", STOP),
        ("Quiero parar, gracias.", STOP),
        ("Vale, lo dejo aquí.", STOP),
        ("No quiero seguir.", STOP),
        ("Para el turno de mañana me viene bien.", NONE),  # "para", the preposition
        ("No quiero parar, sigamos.", NONE),
        ("Uf, esto es muy lento y no me entero.", NONE),  # tone is the classifier's job
        ("Quiero hablar con una persona. Bueno, mejor lo dejo aquí.", HUMAN | STOP),
        ("I want to talk to a real person", HUMAN),
        ("Can I speak with someone?", HUMAN),
        ("I don't want to talk to a person", NONE),
        ("Stop.", STOP),
        ("I'd like to stop here.", STOP),
        ("I'll stop by the store tomorrow.", NONE),
    ],
)
def test_explicit_stop_and_human_requests(text: str, expected: frozenset[Control]) -> None:
    assert explicit_controls(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "Can we continue in English?",
        "Could you switch to English, please?",
        "English please",
        "I'd rather speak English",
        "¿Podemos hablar en inglés?",
        "Mejor en ingles",
        "Inglés, por favor",
    ],
)
def test_explicit_requests_for_english(text: str) -> None:
    assert explicit_controls(text) == {"switch_en"}


@pytest.mark.parametrize(
    "text",
    [
        "Can we go back to Spanish?",
        "In Spanish, please",
        "Mejor en español",
        "En castellano, por favor",
        "¿Puedes hablar español?",
    ],
)
def test_explicit_requests_for_spanish(text: str) -> None:
    assert explicit_controls(text) == {"switch_es"}


@pytest.mark.parametrize(
    "text",
    [
        "Trabajé en Starbucks.",
        "I studied English at school.",
        "Hablo inglés y francés.",
        "I worked in an English-speaking café.",
        "Okay",
        "Sí, me viene bien el turno de closing.",
        "",
    ],
)
def test_a_borrowed_word_or_a_mention_is_not_a_request(text: str) -> None:
    assert explicit_controls(text) == frozenset()


def test_a_language_request_and_a_human_request_in_one_sentence_are_both_seen() -> None:
    assert explicit_controls("In English, please. I want to talk to a person.") == {
        "switch_en",
        "human",
    }


@given(st.text())
def test_explicit_controls_is_total(text: str) -> None:
    assert explicit_controls(text) <= {"stop", "human", "switch_es", "switch_en"}


REQUESTS = ["quiero hablar con una persona", "pásame con alguien real", "quiero terminar"]


@given(st.sampled_from(REQUESTS), st.lists(st.booleans(), min_size=40, max_size=40))
def test_case_and_accents_do_not_change_the_result(request: str, upper: list[bool]) -> None:
    shouted = "".join(c.upper() if u else c for c, u in zip(request, upper, strict=False))
    plain = request.replace("á", "a")
    assert explicit_controls(shouted) == explicit_controls(request)
    assert explicit_controls(plain) == explicit_controls(request) != NONE


FILLER = st.sampled_from(["", "Vale.", "Mira,", "Pues nada.", "Oye, una cosa:"])


@given(FILLER, st.sampled_from(REQUESTS), FILLER)
def test_a_request_survives_surrounding_clauses(before: str, request: str, after: str) -> None:
    assert explicit_controls(f"{before} {request}. {after}") == explicit_controls(request)


@pytest.mark.parametrize(
    ("controls", "current", "expected"),
    [
        (frozenset(), "es", "es"),
        (frozenset({"switch_en"}), "es", "en"),
        (frozenset({"switch_en"}), "en", "en"),
        (frozenset({"switch_es"}), "en", "es"),
        (frozenset({"switch_es", "switch_en"}), "es", "es"),  # ambiguous: no change
        (frozenset({"stop"}), "en", "en"),
    ],
)
def test_requested_language(
    controls: frozenset[Control], current: Language, expected: Language
) -> None:
    assert requested_language(controls, current) == expected


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


async def test_a_language_request_is_recorded_on_the_signal() -> None:
    reply = '{"sentiment": "neutral", "evidence_text": ""}'
    signal = await analyzer(reply).analyze(TurnId("t1"), "In English, please.", "es")
    assert signal is not None and signal.language_switch_to == "en"
    same = await analyzer(reply).analyze(TurnId("t1"), "In English, please.", "en")
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


# ---- plain answers to a read-back ----------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Sí.",
        "Sí, es correcto.",
        "sí sí",
        "Correcto",
        "Vale.",
        "Eso es.",
        "Exacto",
        "Mhmm. Sí, es todo correcto.",
        "Yes.",
        "That's right",
        "Yes, correct.",
    ],
)
def test_a_plain_yes_is_an_affirmation(text: str) -> None:
    assert answer_to_readback(text) == "affirm"


@pytest.mark.parametrize(
    "text", ["No.", "No, no es correcto.", "No es así", "Nope", "That's wrong"]
)
def test_a_plain_no_is_a_denial(text: str) -> None:
    assert answer_to_readback(text) == "deny"


@pytest.mark.parametrize(
    "text",
    [
        "Sí, pero el teléfono es otro",  # a correction rides along: the model handles it
        "No, es el 3 de noviembre",
        "Sí. Sigo. ¿Dónde está la tienda?",
        "Tengo una duda",
        "",
        "Overall, always the time search. C.",
    ],
)
def test_anything_more_than_a_plain_answer_goes_to_the_model(text: str) -> None:
    assert answer_to_readback(text) is None
