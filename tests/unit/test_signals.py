"""Explicit controls (pure patterns: stop, human and language requests), the classifier adapter
and signal freshness."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from cafe_norte.conversation import prompts
from cafe_norte.conversation.signals import (
    QUESTIONS,
    SWITCH_THRESHOLD,
    Control,
    answer_to_readback,
    asks_question,
    chosen_language,
    explicit_controls,
    fresh_sentiment,
    is_farewell,
    requested_language,
)
from cafe_norte.domain.contracts import Sentiment, Signal, TurnId
from cafe_norte.errors import SWITCHABLE, Language

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
        "Do I need to speak Spanish for this job?",
        "¿Hace falta hablar inglés?",
        "No need to switch to Spanish, English is fine.",
        "No hace falta que me hables en inglés, entiendo bien.",
        "I don't speak Spanish.",
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
        # KI-01: everyday ways of saying it is all right, in any order
        "Sí, está todo bien.",
        "Está todo bien.",
        "Está todo bien. Todo correcto.",
        "Todo bien",
        "Todo está bien, perfecto.",
        "Bien, todo correcto, sí.",
        "Está bien, vale.",
        "Todo perfecto.",
        "Sí, eso es, todo bien.",
        "Yes, all good.",
        "All right, that's fine.",
        "Good, all correct.",
        "Yeah, that is right.",
    ],
)
def test_a_plain_yes_is_an_affirmation(text: str) -> None:
    assert answer_to_readback(text) == "affirm"


@pytest.mark.parametrize(
    "text",
    [
        "Sigue.",
        "Sigue, sigue.",
        "Seguimos.",
        "Sí, seguimos.",
        "Vale, sigamos.",
        "Continúa.",
        "Adelante.",
        "No hace falta.",
        "No hace falta, sigue.",
        "Mhmm, sigue adelante.",
        "Carry on.",
        "Yes, carry on.",
        "Go on.",
        "Let's move on.",
        "Keep going.",
        "No need.",
        "Skip it.",
    ],
)
def test_an_explicit_carry_on_is_a_skip(text: str) -> None:
    assert answer_to_readback(text) == "skip"


@pytest.mark.parametrize(
    "text",
    [
        "Sigue, pero el teléfono es otro",  # a correction rides along: the model handles it
        "Sigue. ¿Dónde está la tienda?",
        "No sigas",
        "No, sigue.",  # a bare no rides with nothing: the model reads it
        "No es correcto. Sigue.",  # a correction is never a skip
        "No está bien, sigue",
        "No hace falta que lo repitas, el teléfono es otro",
        "Carry on, but the date is wrong",
    ],
)
def test_a_carry_on_with_something_more_goes_to_the_model(text: str) -> None:
    assert answer_to_readback(text) is None


@pytest.mark.parametrize("text", ["Todo.", "Está.", "Eso.", "Así.", "All.", "Es lo."])
def test_a_yes_made_only_of_weak_words_needs_a_core_yes_word(text: str) -> None:
    assert answer_to_readback(text) is None


@pytest.mark.parametrize(
    "text",
    ["No está todo bien", "Todo bien, no", "No, todo mal", "Not all good", "Todo bien pero no"],
)
def test_a_negation_is_never_a_yes(text: str) -> None:
    assert answer_to_readback(text) != "affirm"


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


# ---- a farewell (D46) ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "¡Hasta luego, Ana!",
        "No, nada más. Muchas gracias, adiós.",
        "Vale, gracias, nos vemos.",
        "Goodbye, Ana! Thank you again!",
        "Gracias, Ana.",  # thanks alone closes too
        "Vale, muchas gracias por todo, hasta pronto.",
    ],
)
def test_a_farewell_is_seen_in_both_languages(text: str) -> None:
    assert is_farewell(text)


@pytest.mark.parametrize(
    "text",
    [
        "Sí, no me lo expliques, he vivido por ahí, muchas gracias.",  # live, 22 October
        "Thank you, Ana! I appreciate your help and I'm looking forward to the interview.",
        "Gracias, una cosa más, el teléfono es otro.",
    ],
)
def test_thanks_beside_other_words_is_the_models(text: str) -> None:
    """Live: "muchas gracias" inside a longer sentence closed the call with no model round,
    and the next four things said failed on an ended session (D59). Only a goodbye that is
    the whole utterance is the runtime's."""
    assert not is_farewell(text)


@pytest.mark.parametrize(
    "text",
    [
        "Vale.",
        "Adiós, pero ¿puedo cambiar la hora?",
        "Hasta luego no, espera, quiero otra hora.",
        "Bye, actually I need to change the interview.",
        "¿Cómo se dice adiós en inglés?",
    ],
)
def test_a_farewell_with_anything_still_to_do_is_not_one(text: str) -> None:
    assert not is_farewell(text)


def test_the_questions_offer_every_sentiment_and_every_language() -> None:
    assert set(QUESTIONS["sentiment"].criteria) == {
        "neutral",
        "positive",
        "frustrated",
        "uncertain",
    }
    assert set(QUESTIONS["reply_language"].criteria) == {*SWITCHABLE, "other"}
    assert set(prompts.languages()) == set(SWITCHABLE)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("¿Podemos hablar en francés?", {"switch_fr"}),
        ("In French, please.", {"switch_fr"}),
        ("Puedes hablar portugués", {"switch_pt"}),
        ("Could we speak German?", {"switch_de"}),
        ("Háblame en italiano", {"switch_it"}),
        ("en rumano, por favor", {"switch_ro"}),
        ("Ucraniano, please", {"switch_uk"}),
        ("I studied French at school.", set()),  # a mention, not a request
        ("Do I need to speak Portuguese?", set()),
        ("No hace falta que me hables en francés.", set()),  # turned down
    ],
)
def test_explicit_requests_for_the_other_languages(text: str, expected: set[Control]) -> None:
    assert explicit_controls(text) == expected


@given(
    st.dictionaries(st.sampled_from([*SWITCHABLE, "other"]), st.floats(0, 1), max_size=11),
    st.sampled_from(SWITCHABLE),
)
def test_chosen_language_switches_only_to_a_likely_other_language(
    probabilities: dict[str, float], current: Language
) -> None:
    chosen = chosen_language(probabilities, current)
    assert chosen in SWITCHABLE
    if chosen != current:
        assert probabilities[chosen] >= SWITCH_THRESHOLD
        assert all(probabilities.get(c, 0.0) <= probabilities[chosen] for c in SWITCHABLE)


def test_chosen_language_examples() -> None:
    assert chosen_language({"es": 0.2, "fr": 0.8}, "es") == "fr"
    assert chosen_language({"es": 0.4, "fr": 0.6}, "es") == "es"  # under the threshold
    assert chosen_language({"es": 0.9}, "es") == "es"
    assert chosen_language({"other": 1.0}, "en") == "en"  # unlisted: keep
    assert chosen_language({}, "en") == "en"


@pytest.mark.parametrize(
    "text",
    [
        "Me gustaría saber cuál es la localización exacta.",
        "¿Dónde está la tienda?",
        "Cuánto se cobra",
        "una pregunta, ¿hay uniforme?",
        "Where is the store?",
        "I'd like to know the pay",
    ],
)
def test_a_question_is_recognised_in_either_language(text: str) -> None:
    assert asks_question(text)


@pytest.mark.parametrize("text", ["Sí.", "Es todo correcto.", "Que sí, que vale.", "Yes, fine."])
def test_an_answer_is_not_a_question(text: str) -> None:
    assert not asks_question(text)


@pytest.mark.parametrize(
    "text",
    [
        "Sí, anótalo para que me contacten.",
        "que alguien del equipo me llame",
        "Please contact me about this.",
        "can someone call me back?",
    ],
)
def test_asking_to_be_contacted_is_a_request_for_a_person(text: str) -> None:
    assert "human" in explicit_controls(text)
