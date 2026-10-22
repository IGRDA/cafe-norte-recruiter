"""The simulated candidate: what it does on each line is decided here, deterministically; the
model only words it. So a correction, a language switch or a question always happens, and on
a line we can name."""

from datetime import UTC, datetime

import pytest
from evals.contracts import Cue, Persona, Speaker, Transcript
from evals.simulator import ModelCandidateSimulator, SimulatedCandidate, SimulatorError, cue

from cafe_norte.model.contracts import ModelEvent, ModelFinished, ModelText
from cafe_norte.model.fake import FakeModel

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


def said(text: str) -> list[ModelEvent]:
    return [ModelText(text=text), ModelFinished(reason="stop")]


async def test_the_model_words_the_cue_from_the_persona_and_the_transcript() -> None:
    model = FakeModel([said('  "Me llamo Lucía Marín."  ')])
    simulator = ModelCandidateSimulator(model)
    line = await simulator.reply(
        PERSONA, Cue(language="es", mood="neutral", ask="¿Hay parking?"), GREETING
    )
    assert line == "Me llamo Lucía Marín."
    (messages,) = model.calls
    system, user = messages[0].content, messages[-1].content
    assert "Lucía Marín" in system and "hours_per_week: 30" in system
    assert "Ana: Hola, soy Ana." in user
    assert "¿Hay parking?" in user and "Spanish" in user


async def test_the_simulator_knows_today_so_a_relative_date_reads_back_right() -> None:
    """A live run is on a real clock: without today the model resolved "next monday" to a
    2023 date and corrected Ana's right read-back (S01 live, 22 October 2026)."""
    model = FakeModel([said("Sí, correcto.")])
    thursday = datetime(2026, 10, 22, 9, tzinfo=UTC)
    simulator = ModelCandidateSimulator(model, clock=lambda: thursday)
    await simulator.reply(PERSONA, Cue(language="es", mood="neutral"), GREETING)
    system = model.calls[0][0].content
    assert "Thursday 22 October 2026" in system
    assert "reads back a detail or a summary" in system


async def test_a_relative_date_fact_is_given_with_the_day_it_means() -> None:
    """Knowing today was not enough: the model still said "lunes 23 de octubre" (a Friday)
    for next Monday (S01 live, 22 October 2026)."""
    model = FakeModel([said("Sí.")])
    thursday = datetime(2026, 10, 22, 9, tzinfo=UTC)
    persona = Persona(facts={"earliest_start_date": "next monday"})
    await ModelCandidateSimulator(model, clock=lambda: thursday).reply(
        persona, Cue(language="es", mood="neutral"), GREETING
    )
    assert "earliest_start_date: next monday (Monday 26 October 2026)" in model.calls[0][0].content


async def test_a_simulator_that_says_nothing_stops_the_run() -> None:
    simulator = ModelCandidateSimulator(FakeModel([said("   ")]))
    with pytest.raises(SimulatorError):
        await simulator.reply(PERSONA, Cue(language="es", mood="neutral"), GREETING)


async def test_the_simulated_candidate_stops_after_withdrawing() -> None:
    model = FakeModel([said("Sí, dime."), said("Lo dejo aquí, gracias.")])
    candidate = SimulatedCandidate(
        ModelCandidateSimulator(model), Persona(facts={}, withdraws_after_turn=1), "es"
    )
    first = await candidate.next_line(GREETING)
    second = await candidate.next_line(after(("candidate", "Sí, dime."), ("ana", "¿Nombre?")))
    assert (first, second) == ("Sí, dime.", "Lo dejo aquí, gracias.")
    assert "leave" in model.calls[-1][-1].content
    assert await candidate.next_line(GREETING) is None
