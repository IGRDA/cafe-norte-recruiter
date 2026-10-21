"""Scenario checks over the final state and transcript."""

from datetime import UTC, date, datetime

from evals.contracts import Check, SessionResult
from evals.scorers import run_check

from cafe_norte.domain.candidate import apply_patch
from cafe_norte.domain.contracts import (
    BriefTarget,
    CandidatePatch,
    CandidateRecord,
    ConfigId,
    Confirmation,
    ConfirmationId,
    Evidence,
    InputId,
    SessionId,
    SessionState,
    TurnId,
)
from cafe_norte.persistence.contracts import TurnRecord

NOW = datetime(2026, 10, 20, tzinfo=UTC)
LINES = ("Me llamo Lucía Marín, sí me interesa.", "Puedo lunes y jueves, 30 horas.")


def turn(role: str, text: str, n: int) -> TurnRecord:
    return TurnRecord(
        turn_id=TurnId(f"t{n}"),
        session_id=SessionId("s"),
        input_id=InputId(f"in-{n}"),
        role="user" if role == "user" else "assistant",
        channel="text",
        language="es",
        text=text,
        started_at=NOW,
    )


def result(
    patch: CandidatePatch | None = None,
    *,
    evidence_text: str = LINES[0],
    brief_status: str | None = None,
    brief_revision: int | None = None,
    lifecycle: str = "active",
    outcome: str | None = None,
    spoken_by_turn: tuple[tuple[str, ...], ...] = (),
) -> SessionResult:
    candidate = CandidateRecord()
    if patch is not None:
        evidence = Evidence(source_turn_id=TurnId("t1"), text=evidence_text)
        candidate = apply_patch(candidate, patch, evidence)
    pending = None
    if brief_status is not None:
        pending = Confirmation(
            confirmation_id=ConfirmationId("k"),
            target=BriefTarget(
                revision=brief_revision if brief_revision is not None else candidate.revision
            ),
            presentation_text="Resumen.",
            presented_turn_id=TurnId("t2"),
            fully_delivered=True,
            status=brief_status,
        )
    state = SessionState(
        session_id=SessionId("s"),
        config_id=ConfigId("chamberi_barista_v1"),
        config_version="1",
        language="es",
        channel="text",
        created_at=NOW,
        lifecycle=lifecycle,
        outcome=outcome,
        candidate=candidate,
        pending_confirmation=pending,
    )
    turns = tuple(turn("user", line, n) for n, line in enumerate(LINES, start=1))
    return SessionResult(state=state, turns=turns, spoken_by_turn=spoken_by_turn)


def test_field_equals_parses_the_expected_value_by_field_type() -> None:
    r = result(
        CandidatePatch(
            name="Lucía Marín",
            hours_per_week=30,
            availability_days=frozenset({"mon", "thu"}),
            earliest_start_date=date(2026, 10, 26),
        )
    )
    assert run_check(
        r, Check(name="field_equals", args={"field": "name", "value": "Lucía Marín"})
    ).ok
    assert run_check(
        r, Check(name="field_equals", args={"field": "hours_per_week", "value": "30"})
    ).ok
    assert run_check(
        r, Check(name="field_equals", args={"field": "availability_days", "value": "thu,mon"})
    ).ok
    assert run_check(
        r, Check(name="field_equals", args={"field": "earliest_start_date", "value": "2026-10-26"})
    ).ok
    wrong = run_check(r, Check(name="field_equals", args={"field": "name", "value": "Ane"}))
    assert not wrong.ok and "Lucía Marín" in wrong.detail


def test_field_status_brief_confirmed_outcome_and_lifecycle() -> None:
    r = result(
        CandidatePatch(name="Lucía"),
        brief_status="confirmed",
        lifecycle="completed",
        outcome="brief_only",
    )
    assert run_check(r, Check(name="field_status", args={"field": "name", "status": "captured"})).ok
    assert run_check(r, Check(name="brief_confirmed")).ok
    assert run_check(r, Check(name="outcome_is", args={"outcome": "brief_only"})).ok
    assert run_check(r, Check(name="lifecycle_is", args={"lifecycle": "completed"})).ok
    stale = result(CandidatePatch(name="Lucía"), brief_status="confirmed", brief_revision=0)
    assert not run_check(stale, Check(name="brief_confirmed")).ok
    assert not run_check(result(), Check(name="brief_confirmed")).ok


def test_no_fabricated_confirmed_values_needs_evidence_from_the_candidates_own_lines() -> None:
    honest = result(CandidatePatch(name="Lucía Marín"))
    assert run_check(honest, Check(name="no_fabricated_confirmed_values")).ok
    invented = result(CandidatePatch(name="Lucía Marín"), evidence_text="the model made this up")
    verdict = run_check(invented, Check(name="no_fabricated_confirmed_values"))
    assert not verdict.ok and "name" in verdict.detail


def test_max_repeated_questions_counts_a_question_spoken_in_two_turns() -> None:
    repeated = result(spoken_by_turn=(("¿Cómo te llamas?",), ("Vale.", "¿Cómo te llamas?")))
    assert not run_check(repeated, Check(name="max_repeated_questions", args={"max": "0"})).ok
    assert run_check(repeated, Check(name="max_repeated_questions", args={"max": "1"})).ok
    distinct = result(spoken_by_turn=(("¿Cómo te llamas?",), ("¿Tienes permiso?",)))
    assert run_check(distinct, Check(name="max_repeated_questions", args={"max": "0"})).ok
    # The system's own read-back questions repeat by design (a brief presented again after a
    # correction); only the model's questions count.
    readbacks = result(
        spoken_by_turn=(
            ("Te resumo lo que tengo.", "¿Es todo correcto?"),
            ("Te resumo lo que tengo.", "¿Es todo correcto?"),
            ("He apuntado el teléfono +34 612 345 678.", "¿Es correcto?"),
            ("He apuntado que podrías empezar el lunes.", "¿Es correcto?"),
        )
    )
    assert run_check(readbacks, Check(name="max_repeated_questions", args={"max": "0"})).ok
