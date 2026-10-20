"""S01, the Spanish happy path, replayed offline turn by turn.

The candidate lines come from evals/cases/scenarios/S01.yaml. The fake model's script is what
the prompt instructs a well-behaved model to do: one ``update_candidate`` per informative turn
with every field stated in it, then a short answer. PR A covers collection; the brief,
confirmation and ending extend this file in PR B."""

import json
from pathlib import Path
from typing import Any

import yaml

from cafe_norte.conversation.contracts import StateUpdated, TurnFinished
from cafe_norte.domain.candidate import unfinished_fields
from cafe_norte.domain.fields import value_of
from cafe_norte.model.contracts import ModelEvent, ModelFinished, ToolCall
from tests.support import ROOT
from tests.test_runtime import SESSION, Harness, says

SCENARIO = yaml.safe_load((ROOT / "evals/cases/scenarios/S01.yaml").read_text())
LINES: list[str] = SCENARIO["scripted_turns"]


def update(call_id: str, evidence: str, **patch: Any) -> list[ModelEvent]:
    args = {"patch": patch, "evidence_text": evidence}
    call = ToolCall(call_id=call_id, name="update_candidate", arguments_json=json.dumps(args))
    return [call, ModelFinished(reason="tool_calls")]


SCRIPT: list[list[ModelEvent]] = [
    # "Sí, me viene bien."
    says("Genial. ¿Cómo te llamas y te interesa el puesto de barista?"),
    # "Me llamo Lucía Marín, sí me interesa el puesto."
    update("c1", LINES[1], name="Lucía Marín", interest="yes"),
    says("Encantada, Lucía. ¿Tienes permiso de trabajo y qué disponibilidad tienes?"),
    # "Tengo permiso de trabajo. Puedo lunes, martes y jueves por la mañana, unas 30 horas."
    update(
        "c2",
        LINES[2],
        work_authorization="yes",
        availability_days=["mon", "tue", "thu"],
        availability_shifts=["morning"],
        hours_per_week=30,
    ),
    says("Perfecto. ¿Cuándo podrías empezar y qué experiencia tienes?"),
    # "Podría empezar el lunes que viene. He trabajado dos años en una cafetería."
    update(
        "c3",
        LINES[3],
        earliest_start_date="2026-10-26",
        experience="dos años en una cafetería",
    ),
    says("Gracias, Lucía. Ya tengo todo lo que necesito por ahora."),
]


async def test_s01_collects_the_whole_record_in_four_candidate_turns() -> None:
    h = Harness(SCRIPT)
    await h.open_session()
    _ = [e async for e in h.runtime.open_session(SESSION)]
    revisions: list[int] = []
    for index, line in enumerate(LINES[:4]):
        events = await h.run(line, f"in-{index}")
        assert isinstance(events[-1], TurnFinished), events[-1]
        revisions.extend(e.revision for e in events if isinstance(e, StateUpdated))

    assert revisions == [1, 2, 3]
    state = await h.store.sessions.get(SESSION)
    assert state is not None
    candidate = state.candidate
    facts = SCENARIO["persona"]["facts"]
    assert value_of(candidate.name) == facts["name"]
    assert value_of(candidate.interest) == "yes"
    assert value_of(candidate.work_authorization) == facts["work_authorization"]
    assert value_of(candidate.availability_days) == frozenset(facts["availability_days"].split(","))
    assert value_of(candidate.availability_shifts) == frozenset({facts["availability_shifts"]})
    assert value_of(candidate.hours_per_week) == int(facts["hours_per_week"])
    assert str(value_of(candidate.earliest_start_date)) == "2026-10-26"  # next Monday from 20 Oct
    # The persona fact is richer than what the candidate line says; the record keeps her words.
    assert value_of(candidate.experience) == "dos años en una cafetería"
    assert unfinished_fields(candidate) == ()
    assert candidate.contact_phone.status == "unset"  # optional, never required
    # Evidence always points at the candidate's own finalized words.
    assert candidate.name.status == "captured" and candidate.name.evidence.text == LINES[1]
    assert state.review_flags == ()


def test_the_scenario_file_is_the_source_of_the_lines() -> None:
    assert Path(ROOT / "evals/cases/scenarios/S01.yaml").exists()
    assert len(LINES) == 8 and LINES[1].startswith("Me llamo Lucía Marín")
