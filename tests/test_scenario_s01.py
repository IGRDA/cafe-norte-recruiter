"""S01, the Spanish happy path, replayed offline turn by turn.

The candidate lines come from evals/cases/scenarios/S01.yaml. The fake model's script is what
the prompt instructs a well-behaved model to do: one ``update_candidate`` per informative turn
with every field stated in it, then a short answer. PR A covers collection; the brief,
confirmation and ending extend this file in PR B."""

import json
from pathlib import Path
from typing import Any

import yaml

from cafe_norte.conversation.contracts import AssistantText, StateUpdated, TurnFailed, TurnFinished
from cafe_norte.domain.candidate import unfinished_fields
from cafe_norte.domain.contracts import BriefTarget
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


def tool(call_id: str, name: str, **arguments: Any) -> list[ModelEvent]:
    call = ToolCall(call_id=call_id, name=name, arguments_json=json.dumps(arguments, default=str))
    return [call, ModelFinished(reason="tool_calls")]


FULL_SCRIPT: list[list[ModelEvent]] = [
    *SCRIPT[:5],
    # "Podría empezar el lunes que viene. He trabajado dos años en una cafetería."
    update(
        "c3", LINES[3], earliest_start_date="2026-10-26", experience="dos años en una cafetería"
    ),
    says(""),  # the date read-back was spoken by update_candidate itself
    # "Sí, todo correcto."  → the date read-back; then nothing is left: the brief
    tool("f1", "confirm_field", answer="affirm"),
    tool("p2", "present_confirmation", target="brief"),
    says(""),
    # "Sí, quiero entrevista." → the brief is confirmed, the wish noted, the session ends
    tool("b1", "confirm_brief", answer="affirm"),
    update("c4", LINES[5], note="quiere entrevista"),
    tool("e1", "end_session", reason="candidate_done"),
    says("Gracias, Lucía. En esta versión aún no reservo entrevistas. Hasta pronto."),
]


async def test_s01_runs_to_a_confirmed_brief_and_a_completed_session() -> None:
    h = Harness(FULL_SCRIPT)
    await h.open_session()
    _ = [e async for e in h.runtime.open_session(SESSION)]
    spoken: dict[int, list[str]] = {}
    for index, line in enumerate(LINES[:6]):
        events = await h.run(line, f"in-{index}")
        assert isinstance(events[-1], TurnFinished), (index, events[-1])
        spoken[index] = [e.text for e in events if isinstance(e, AssistantText)]

    # Turn 4: the date was read back verbatim and is pending, delivered.
    assert spoken[3] == [
        "He apuntado que podrías empezar el lunes 26 de octubre de 2026.",
        "¿Es correcto?",
    ]
    # Turn 5: the date is confirmed and the brief presented at revision 3.
    assert spoken[4][0] == "Te resumo lo que tengo." and spoken[4][-1] == "¿Es todo correcto?"
    # Turn 6: one goodbye, nothing else.
    assert spoken[5] == [
        "Gracias, Lucía.",
        "En esta versión aún no reservo entrevistas.",
        "Hasta pronto.",
    ]

    state = await h.store.sessions.get(SESSION)
    assert state is not None
    assert (state.lifecycle, state.outcome) == ("completed", "brief_only")
    assert state.candidate.earliest_start_date.status == "confirmed"
    assert state.candidate.notes == ("quiere entrevista",)
    pending = state.pending_confirmation
    assert pending is not None and pending.status == "confirmed"
    assert isinstance(pending.target, BriefTarget) and pending.target.revision == 3
    assert pending.presentation_text == " ".join(spoken[4])
    # no_fabricated_confirmed_values: every value's evidence is one of the candidate's lines.
    for name in ("name", "interest", "work_authorization", "earliest_start_date", "experience"):
        field = getattr(state.candidate, name)
        assert field.evidence.text in LINES, name

    # The session is over: a further turn is refused and nothing is persisted.
    again = await h.run("¿Sigues ahí?", "in-9")
    assert isinstance(again[0], TurnFailed) and again[0].code == "session_ended"


async def test_a_correction_after_the_brief_invalidates_it_and_it_is_presented_again() -> None:
    script: list[list[ModelEvent]] = [
        *FULL_SCRIPT[:10],  # up to and including the brief presented on turn 5
        # "Perdona, son 25 horas." → corrected, the brief is void, presented again
        update("c5", "Perdona, son 25 horas.", hours_per_week=25),
        tool("p3", "present_confirmation", target="brief"),
        says(""),
        # "Sí, correcto." → confirmed at the new revision
        tool("b2", "confirm_brief", answer="affirm"),
        says("Perfecto."),
    ]
    h = Harness(script)
    await h.open_session()
    _ = [e async for e in h.runtime.open_session(SESSION)]
    for index, line in enumerate(LINES[:5]):
        await h.run(line, f"in-{index}")
    corrected = await h.run("Perdona, son 25 horas.", "in-5")
    updates = [e for e in corrected if isinstance(e, StateUpdated)]
    assert updates[0].revision == 4
    assert updates[0].pending_confirmation is not None
    assert updates[0].pending_confirmation.status == "invalidated"
    represented = updates[-1].pending_confirmation
    assert represented is not None and isinstance(represented.target, BriefTarget)
    assert represented.target.revision == 4
    assert any("unas 25 horas" in e.text for e in corrected if isinstance(e, AssistantText))
    confirmed = await h.run("Sí, correcto.", "in-6")
    final = [e for e in confirmed if isinstance(e, StateUpdated)][-1].pending_confirmation
    assert final is not None and final.status == "confirmed"
    assert isinstance(final.target, BriefTarget) and final.target.revision == 4


def test_the_scenario_file_is_the_source_of_the_lines() -> None:
    assert Path(ROOT / "evals/cases/scenarios/S01.yaml").exists()
    assert len(LINES) == 8 and LINES[1].startswith("Me llamo Lucía Marín")
