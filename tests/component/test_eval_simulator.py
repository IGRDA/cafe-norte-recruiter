"""The simulated candidate: what it does on each line is decided here, deterministically; the
model only words it. So a correction, a language switch or a question always happens, and on
a line we can name."""

from datetime import UTC, datetime

import pytest
from evals.contracts import Cue, Persona
from evals.simulator import ModelCandidateSimulator, SimulatedCandidate, SimulatorError

from cafe_norte.model.fake import FakeModel
from tests.support.evals import GREETING, PERSONA, after
from tests.support.harness import says


async def test_the_model_words_the_cue_from_the_persona_and_the_transcript() -> None:
    model = FakeModel([says('  "Me llamo Lucía Marín."  ')])
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
    model = FakeModel([says("Sí, correcto.")])
    thursday = datetime(2026, 10, 22, 9, tzinfo=UTC)
    simulator = ModelCandidateSimulator(model, clock=lambda: thursday)
    await simulator.reply(PERSONA, Cue(language="es", mood="neutral"), GREETING)
    system = model.calls[0][0].content
    assert "Thursday 22 October 2026" in system
    assert "reads back a detail or a summary" in system


async def test_a_relative_date_fact_is_given_with_the_day_it_means() -> None:
    """Knowing today was not enough: the model still said "lunes 23 de octubre" (a Friday)
    for next Monday (S01 live, 22 October 2026)."""
    model = FakeModel([says("Sí.")])
    thursday = datetime(2026, 10, 22, 9, tzinfo=UTC)
    persona = Persona(facts={"earliest_start_date": "next monday"})
    await ModelCandidateSimulator(model, clock=lambda: thursday).reply(
        persona, Cue(language="es", mood="neutral"), GREETING
    )
    assert "earliest_start_date: next monday (Monday 26 October 2026)" in model.calls[0][0].content


async def test_a_simulator_that_says_nothing_stops_the_run() -> None:
    simulator = ModelCandidateSimulator(FakeModel([says("   ")]))
    with pytest.raises(SimulatorError):
        await simulator.reply(PERSONA, Cue(language="es", mood="neutral"), GREETING)


async def test_the_simulated_candidate_stops_after_withdrawing() -> None:
    model = FakeModel([says("Sí, dime."), says("Lo dejo aquí, gracias.")])
    candidate = SimulatedCandidate(
        ModelCandidateSimulator(model), Persona(facts={}, withdraws_after_turn=1), "es"
    )
    first = await candidate.next_line(GREETING)
    second = await candidate.next_line(after(("candidate", "Sí, dime."), ("ana", "¿Nombre?")))
    assert (first, second) == ("Sí, dime.", "Lo dejo aquí, gracias.")
    assert "leave" in model.calls[-1][-1].content
    assert await candidate.next_line(GREETING) is None
