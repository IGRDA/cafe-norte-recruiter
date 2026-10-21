"""The simulated candidate: what it does on each line is decided here, deterministically; the
model only words it. So a correction, a language switch or a question always happens, and on
a line we can name."""

from evals.contracts import Cue, Persona, Speaker, Transcript
from evals.simulator import cue

PERSONA = Persona(
    facts={"name": "Lucía Marín", "hours_per_week": "30"},
    corrections=(("hours_per_week", "25"),),
    asks=("¿Cuántas horas son?", "¿Hay parking?"),
)
GREETING: Transcript = (("ana", "Hola, soy Ana. ¿Te viene bien ahora?"),)
BRIEF = "Te leo el resumen. Lucía Marín, 30 horas. ¿Es todo correcto?"


def after(*lines: tuple[Speaker, str]) -> Transcript:
    return (*GREETING, *lines)


def test_the_first_line_just_answers_in_the_session_language() -> None:
    assert cue(PERSONA, "es", GREETING) == Cue(language="es", mood="neutral")


def test_questions_are_asked_one_per_line_from_the_second() -> None:
    first = after(("candidate", "Sí."), ("ana", "¿Cómo te llamas?"))
    assert cue(PERSONA, "es", first).ask == "¿Cuántas horas son?"
    second = after(*first[1:], ("candidate", "Lucía."), ("ana", "¿Tienes permiso?"))
    assert cue(PERSONA, "es", second).ask == "¿Hay parking?"
    third = after(*second[1:], ("candidate", "Sí."), ("ana", "¿Qué días?"))
    assert cue(PERSONA, "es", third).ask is None


def test_corrections_answer_the_first_brief_and_only_the_first() -> None:
    first_brief = after(("candidate", "Sí."), ("ana", BRIEF))
    assert cue(PERSONA, "es", first_brief).corrections == (("hours_per_week", "25"),)
    second_brief = after(*first_brief[1:], ("candidate", "Son 25."), ("ana", BRIEF))
    assert cue(PERSONA, "es", second_brief).corrections == ()


def test_the_brief_is_recognised_in_english_too() -> None:
    brief = after(("candidate", "Yes."), ("ana", "Here is the summary. Is all of that correct?"))
    assert cue(PERSONA, "en", brief).corrections == (("hours_per_week", "25"),)


def test_the_language_switches_after_the_named_line_and_stays() -> None:
    persona = PERSONA.model_copy(update={"switch_language_after_turn": 2, "asks": ()})
    two = after(("candidate", "Sí."), ("ana", "¿Nombre?"))
    assert cue(persona, "es", two).language == "es"
    three = after(*two[1:], ("candidate", "Lucía."), ("ana", "¿Permiso?"))
    assert cue(persona, "es", three).language == "en"
    assert cue(persona, "en", three).language == "es"


def test_a_withdrawal_comes_after_the_named_line() -> None:
    persona = Persona(facts={}, withdraws_after_turn=1)
    assert not cue(persona, "es", GREETING).withdraw
    assert cue(persona, "es", after(("candidate", "Sí."), ("ana", "¿Nombre?"))).withdraw


def test_mood_comes_from_the_persona() -> None:
    persona = Persona(facts={}, mood="frustrated")
    assert cue(persona, "es", GREETING).mood == "frustrated"
