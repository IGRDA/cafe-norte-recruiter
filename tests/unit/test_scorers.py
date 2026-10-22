"""Scenario checks over the final state and transcript."""

from datetime import UTC, date, datetime

from evals.contracts import Check, CheckResult, Persona, SessionResult
from evals.scorers import INVARIANTS, _parse, checks_for, extraction_accuracy, run_check

from cafe_norte.domain.candidate import apply_patch
from cafe_norte.domain.contracts import (
    Booking,
    BriefTarget,
    CandidatePatch,
    CandidateRecord,
    ConfigId,
    Confirmation,
    ConfirmationId,
    Evidence,
    InputId,
    ReviewWaived,
    SessionId,
    SessionState,
    SlotId,
    TurnId,
    YearMonth,
)
from cafe_norte.persistence.contracts import TurnRecord
from tests.support.builders import FULL

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
    booking: Booking | None = None,
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
        brief_confirmed_revision=(
            pending.target.revision
            if pending is not None
            and pending.status == "confirmed"
            and isinstance(pending.target, BriefTarget)
            else None
        ),
        booking=booking,
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


def test_booking_checks_read_the_committed_reservation() -> None:
    booked = result(
        booking=Booking(
            slot_id=SlotId("chamberi_barista_v1-2026-10-21-1030"),
            config_id=ConfigId("chamberi_barista_v1"),
            starts_at_utc=NOW,
            confirmation_id=ConfirmationId("k"),
            idempotency_key="key",
            committed_at=NOW,
        )
    )
    assert run_check(booked, Check(name="booking_present")).ok
    assert not run_check(booked, Check(name="booking_absent")).ok
    assert run_check(result(), Check(name="booking_absent")).ok
    assert not run_check(result(), Check(name="booking_present")).ok


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


def test_tool_ok_reads_what_a_tool_answered_on_a_turn() -> None:
    r = result().model_copy(
        update={
            "tools_by_turn": ((), (("reserve_interview", False), ("present_confirmation", True)))
        }
    )
    refused = Check(name="tool_ok", args={"turn": "2", "tool": "reserve_interview", "ok": "false"})
    assert run_check(r, refused).ok
    wrong = Check(name="tool_ok", args={"turn": "2", "tool": "reserve_interview", "ok": "true"})
    assert not run_check(r, wrong).ok
    absent = Check(name="tool_ok", args={"turn": "1", "tool": "reserve_interview", "ok": "false"})
    assert not run_check(r, absent).ok


def test_tool_ok_holds_for_every_call_of_the_tool_on_that_turn() -> None:
    r = result().model_copy(
        update={"tools_by_turn": ((("reserve_interview", False), ("reserve_interview", True)),)}
    )
    for ok in ("true", "false"):
        check = Check(name="tool_ok", args={"turn": "1", "tool": "reserve_interview", "ok": ok})
        assert not run_check(r, check).ok


def test_turn_failed_names_the_code_a_turn_ended_with() -> None:
    r = result().model_copy(update={"failed_by_turn": ("", "provider_unavailable")})
    assert run_check(
        r, Check(name="turn_failed", args={"turn": "2", "code": "provider_unavailable"})
    ).ok
    assert not run_check(
        r, Check(name="turn_failed", args={"turn": "1", "code": "provider_unavailable"})
    ).ok
    assert run_check(r, Check(name="turn_failed", args={"turn": "1", "code": "none"})).ok


def test_brief_unconfirmed_fails_once_the_candidate_confirmed_a_brief() -> None:
    patch = CandidatePatch(name="Lucía Marín")
    open_brief = result(patch, brief_status="pending")
    assert run_check(open_brief, Check(name="brief_unconfirmed")).ok
    confirmed = result(patch, brief_status="confirmed")
    assert not run_check(confirmed, Check(name="brief_unconfirmed")).ok


def test_readback_assurance_reads_how_the_pending_read_back_was_confirmed() -> None:
    heard = result(brief_status="confirmed")
    assert run_check(heard, Check(name="readback_assurance", args={"assurance": "heard"})).ok
    assert state_with_review(heard, "waived").ok
    assert not run_check(heard, Check(name="readback_assurance", args={"assurance": "waived"})).ok
    pending = result(brief_status="pending")
    assert not run_check(pending, Check(name="readback_assurance", args={"assurance": "heard"})).ok


def state_with_review(heard: SessionResult, stage: str) -> CheckResult:
    pending = heard.state.pending_confirmation
    assert pending is not None
    waived = pending.model_copy(update={"review": ReviewWaived(turn_id=TurnId("t3"))})
    state = heard.state.model_copy(update={"pending_confirmation": waived})
    check = Check(name="readback_assurance", args={"assurance": stage})
    return run_check(heard.model_copy(update={"state": state}), check)


def test_readback_said_whole_counts_the_turns_that_said_the_pending_text_in_full() -> None:
    once = result(brief_status="pending", spoken_by_turn=(("Resumen.",), ("¿Algo más?",)))
    assert run_check(once, Check(name="readback_said_whole", args={"max": "1"})).ok
    twice = result(brief_status="pending", spoken_by_turn=(("Resumen.",), ("Resumen.",)))
    assert not run_check(twice, Check(name="readback_said_whole", args={"max": "1"})).ok
    assert run_check(twice, Check(name="readback_said_whole", args={"max": "2"})).ok


def test_the_check_after_each_part_of_a_review_is_not_a_repeated_question() -> None:
    parts = result(
        spoken_by_turn=(("Te llamas Lucía.", "¿Está bien?"), ("Tienes permiso.", "¿Está bien?"))
    )
    assert run_check(parts, Check(name="max_repeated_questions", args={"max": "0"})).ok


def test_a_relative_start_date_resolves_against_the_session_day() -> None:
    """Live runs happen on a real clock: ``next monday`` from Tuesday 20 October is the 26th."""
    r = result(CandidatePatch(earliest_start_date=date(2026, 10, 26)))
    check = Check(
        name="field_equals", args={"field": "earliest_start_date", "value": "next monday"}
    )
    assert run_check(r, check).ok
    tuesday = Check(
        name="field_equals", args={"field": "earliest_start_date", "value": "next tuesday"}
    )
    assert run_check(result(CandidatePatch(earliest_start_date=date(2026, 10, 27))), tuesday).ok


def test_sources_shown_on_any_turn_is_the_turn_free_grounding_check() -> None:
    r = result().model_copy(update={"sources_by_turn": ((), ("offer_chamberi#horas-1",), ())})
    shown = Check(name="sources_shown_on_any_turn", args={"section_prefix": "offer_chamberi#horas"})
    other = Check(name="sources_shown_on_any_turn", args={"section_prefix": "offer_arganzuela"})
    assert run_check(r, shown).ok
    assert not run_check(r, other).ok


PERSONA = Persona(
    facts={
        "name": "Lucía Marín",
        "work_authorization": "yes",
        "availability_days": "mon,thu",
        "hours_per_week": "30",
        "earliest_start_date": "next monday",
        "experience": "dos años en una cafetería",  # free text: not an exact-match fact
    },
    corrections=(("hours_per_week", "25"),),
)


def test_extraction_counts_structured_facts_after_corrections_and_names_the_misses() -> None:
    r = result(
        CandidatePatch(
            name="lucía marín ",
            work_authorization="yes",
            availability_days=frozenset({"mon", "thu"}),
            hours_per_week=30,  # the correction to 25 was missed
            earliest_start_date=date(2026, 10, 26),
            experience="dos años",
        )
    )
    extraction = extraction_accuracy(PERSONA, r.state)
    assert (extraction.correct, extraction.supplied) == (4, 5)
    assert extraction.misses == ("hours_per_week: expected 25, got 30",)


def test_a_declined_fact_is_not_supplied() -> None:
    persona = PERSONA.model_copy(update={"declines": ("hours_per_week",), "corrections": ()})
    extraction = extraction_accuracy(persona, result().state)
    assert extraction.supplied == 4
    assert extraction.correct == 0


def test_claims_saved_without_save_finds_a_save_said_with_nothing_saved() -> None:
    """Ignacio's call: "Guardo que puedes trabajar los fines de semana." in a turn with no tool
    call; the save came a turn later (D58)."""
    said = ("Guardo que puedes trabajar los fines de semana.", "¿Quieres que lo deje anotado?")
    check = Check(name="claims_saved_without_save")
    early = result(spoken_by_turn=((), said)).model_copy(update={"tools_by_turn": ((), ())})
    verdict = run_check(early, check)
    assert not verdict.ok and "Guardo que" in verdict.detail
    saved = early.model_copy(update={"tools_by_turn": ((), (("update_candidate", True),))})
    assert run_check(saved, check).ok
    refused = early.model_copy(update={"tools_by_turn": ((), (("update_candidate", False),))})
    assert not run_check(refused, check).ok
    asked = result(spoken_by_turn=(("¿Quieres que lo deje anotado?",),))
    assert run_check(asked, check).ok  # an offer to save is not a claim


def test_a_month_reference_compares_at_month_precision() -> None:
    assert _parse("earliest_start_date", "2027-01", date(2026, 10, 20)) == YearMonth(
        year=2027, month=1
    )


# ---- the invariants every scenario runs (D64): each one fed the failure of 22 October ----------


def test_every_scenario_gets_the_invariants_once() -> None:
    own = (
        Check(name="goodbye_ends_session"),
        Check(name="lifecycle_is", args={"lifecycle": "stopped"}),
    )
    names = [c.name for c in checks_for(own)]
    assert names.count("goodbye_ends_session") == 1
    assert {c.name for c in INVARIANTS} <= set(names)


def test_a_sentence_said_twice_in_one_turn_fails() -> None:
    said = "Eso es todo, gracias. Ahora te leo un resumen y me confirmas si está correcto."
    bad = result(spoken_by_turn=(("¿Cómo te llamas?",), (said, said)))
    check = run_check(bad, Check(name="no_sentence_twice_in_a_turn"))
    assert not check.ok and "turn 2" in check.detail
    fine = result(spoken_by_turn=((said,), (said,), ("Sí.", "Sí.")))  # other turns; short words
    assert run_check(fine, Check(name="no_sentence_twice_in_a_turn")).ok


def test_a_goodbye_that_leaves_the_session_open_fails() -> None:
    r = result()
    goodbye = r.turns + (turn("user", "Gracias, adiós.", 9),)
    open_call = r.model_copy(update={"turns": goodbye})
    assert not run_check(open_call, Check(name="goodbye_ends_session")).ok
    ended = result(lifecycle="stopped", outcome="incomplete")
    assert run_check(
        ended.model_copy(update={"turns": goodbye}), Check(name="goodbye_ends_session")
    ).ok


def test_a_complete_record_whose_brief_was_never_read_fails() -> None:
    never_read = result(FULL)
    assert not run_check(never_read, Check(name="brief_presented_once_complete")).ok
    read = result(FULL, brief_status="pending")
    assert run_check(read, Check(name="brief_presented_once_complete")).ok
    capped = result(FULL, lifecycle="abandoned", outcome="incomplete")
    assert run_check(capped, Check(name="brief_presented_once_complete")).ok


def test_a_turn_that_failed_internally_fails() -> None:
    r = result().model_copy(update={"failed_by_turn": ("", "internal_error")})
    assert not run_check(r, Check(name="no_internal_failure")).ok
    r = result().model_copy(update={"failed_by_turn": ("", "timeout")})
    assert run_check(r, Check(name="no_internal_failure")).ok  # a provider timeout is not a bug
