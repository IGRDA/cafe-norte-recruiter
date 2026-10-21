"""Pure scorers over a fake run's result. Each check name maps to one function.

Checks that need retrieval, booking or the export document raise ``NotImplementedError`` with
the stage that brings them, so a scenario cannot silently pass on an unimplemented check."""

from collections import Counter
from collections.abc import Callable
from datetime import date
from functools import cache
from typing import get_args

from cafe_norte.conversation import prompts
from cafe_norte.domain.confirmation import assurance
from cafe_norte.domain.contracts import CandidateFieldName, Captured, Confirmed
from cafe_norte.domain.fields import value_of
from cafe_norte.errors import Language
from evals.contracts import Check, CheckResult, SessionResult

CHECKS = (
    "brief_confirmed",
    "brief_unconfirmed",
    "booking_present",
    "booking_absent",
    "field_equals",
    "field_status",
    "lifecycle_is",
    "no_fabricated_confirmed_values",
    "review_flag_present",
    "outcome_is",
    "language_of_last_assistant_turn",
    "sources_shown_for_policy_answer",
    "no_cross_store_sources",
    "max_repeated_questions",
    "signal_recorded",
    "said_control_reply",
    "tool_ok",
    "turn_failed",
)

SET_FIELDS = {"availability_days", "availability_shifts"}
INT_FIELDS = {"hours_per_week"}
DATE_FIELDS = {"earliest_start_date"}


def run_check(result: SessionResult, check: Check) -> CheckResult:
    scorer = SCORERS.get(check.name)
    if scorer is None:
        raise NotImplementedError(f"check {check.name!r}: {LATER.get(check.name, 'unknown check')}")
    ok, detail = scorer(result, check)
    return CheckResult(name=check.name, ok=ok, detail=detail)


# ---- scorers -------------------------------------------------------------------------------------


def _field_equals(result: SessionResult, check: Check) -> tuple[bool, str]:
    field = _field(check)
    actual = value_of(getattr(result.state.candidate, field))
    expected = _parse(field, check.args["value"])
    return actual == expected, f"{field}: expected {expected!r}, got {actual!r}"


def _field_status(result: SessionResult, check: Check) -> tuple[bool, str]:
    field = _field(check)
    status = getattr(result.state.candidate, field).status
    return status == check.args["status"], f"{field}: expected {check.args['status']}, got {status}"


def _brief_confirmed(result: SessionResult, check: Check) -> tuple[bool, str]:
    confirmed = result.state.brief_confirmed_revision
    current = result.state.candidate.revision
    if confirmed is None:
        return False, "no brief confirmation on record"
    return confirmed == current, f"brief confirmed at revision {confirmed}, record at {current}"


def _brief_unconfirmed(result: SessionResult, check: Check) -> tuple[bool, str]:
    confirmed = result.state.brief_confirmed_revision
    return confirmed is None, f"brief confirmed at revision {confirmed}"


def _booking_present(result: SessionResult, check: Check) -> tuple[bool, str]:
    booking = result.state.booking
    if booking is None:
        return False, "no booking"
    same_store = booking.config_id == result.state.config_id
    return same_store and booking.simulated, f"booking {booking.slot_id}, store match {same_store}"


def _booking_absent(result: SessionResult, check: Check) -> tuple[bool, str]:
    booking = result.state.booking
    return booking is None, "no booking" if booking is None else f"booking {booking.slot_id}"


def _outcome_is(result: SessionResult, check: Check) -> tuple[bool, str]:
    outcome = result.state.outcome
    return outcome == check.args["outcome"], f"expected {check.args['outcome']}, got {outcome}"


def _lifecycle_is(result: SessionResult, check: Check) -> tuple[bool, str]:
    lifecycle = result.state.lifecycle
    return lifecycle == check.args[
        "lifecycle"
    ], f"expected {check.args['lifecycle']}, got {lifecycle}"


def _no_fabricated(result: SessionResult, check: Check) -> tuple[bool, str]:
    """Every captured or confirmed value points at words the candidate actually said."""
    lines = result.candidate_lines
    fabricated = [
        name
        for name in type(result.state.candidate).model_fields
        if isinstance(field := getattr(result.state.candidate, name), Captured | Confirmed)
        and field.evidence.text not in lines
    ]
    return not fabricated, f"evidence not in the candidate's lines: {fabricated or 'none'}"


def _max_repeated_questions(result: SessionResult, check: Check) -> tuple[bool, str]:
    """A question is repeated when the same text is spoken in two different turns. The
    system's own read-back questions are exempt: a brief presented again after a correction
    repeats them by design."""
    system_questions = _system_questions()
    turns_per_question: Counter[str] = Counter()
    for sentences in result.spoken_by_turn:
        for question in {s for s in sentences if "?" in s and s not in system_questions}:
            turns_per_question[question] += 1
    repeated = {q: n for q, n in turns_per_question.items() if n > 1}
    limit = int(check.args.get("max", "0"))
    return len(repeated) <= limit, f"repeated questions: {repeated or 'none'} (max {limit})"


def _sources_shown(result: SessionResult, check: Check) -> tuple[bool, str]:
    """Turn ``turn`` (1-based candidate line) showed a chunk of ``section_prefix``."""
    turn, prefix = int(check.args["turn"]), check.args["section_prefix"]
    shown = result.sources_by_turn[turn - 1] if turn <= len(result.sources_by_turn) else ()
    return any(
        s.startswith(prefix) for s in shown
    ), f"turn {turn} showed {list(shown) or 'nothing'}"


def _no_cross_store_sources(result: SessionResult, check: Check) -> tuple[bool, str]:
    """Every chunk ever shown belongs to a document of this session's configuration."""
    foreign = sorted(
        {s for shown in result.sources_by_turn for s in shown}
        - {
            s
            for shown in result.sources_by_turn
            for s in shown
            if s.split("#")[0] in result.allowed_doc_ids
        }
    )
    return not foreign, f"sources outside the configuration: {foreign or 'none'}"


def _review_flag_present(result: SessionResult, check: Check) -> tuple[bool, str]:
    kinds = [f.kind for f in result.state.review_flags]
    wanted = check.args["kind"]
    return wanted in kinds, f"review flags: {kinds or 'none'} (wanted {wanted})"


def _language_of_last_assistant_turn(result: SessionResult, check: Check) -> tuple[bool, str]:
    last = next((t for t in reversed(result.turns) if t.role == "assistant"), None)
    language = last.language if last is not None else None
    wanted = check.args["language"]
    return language == wanted, f"expected {wanted}, got {language}"


def _brief_language(result: SessionResult, check: Check) -> tuple[bool, str]:
    """The last brief Ana read back came from the ``language`` table, word for word. Read from
    the transcript: after a booking the pending confirmation is the slot, not the brief."""
    intros = {
        language: prompts.table("brief", language)["intro"] for language in get_args(Language)
    }
    briefs = [
        t.text
        for t in result.turns
        if t.role == "assistant" and any(t.text.startswith(intro) for intro in intros.values())
    ]
    if not briefs:
        return False, "no brief on record"
    wanted: Language = "en" if check.args["language"] == "en" else "es"
    return briefs[-1].startswith(intros[wanted]), f"brief: {briefs[-1][:40]}…"


def _signal_recorded(result: SessionResult, check: Check) -> tuple[bool, str]:
    """The classifier's verdict for candidate line ``turn`` (1-based) has ``sentiment``."""
    turn_id = _user_turn_ids(result)[int(check.args["turn"]) - 1]
    found = [s.sentiment for s in result.signals if s.turn_id == turn_id]
    wanted = check.args["sentiment"]
    detail = f"turn {check.args['turn']} signals: {found or 'none'} (wanted {wanted})"
    return found == [wanted], detail


def _said_control_reply(result: SessionResult, check: Check) -> tuple[bool, str]:
    """The fixed reply to an explicit ``control`` was said word for word on ``turn``."""
    reply = prompts.table("controls", result.state.language)[check.args["control"]]
    said = " ".join(result.spoken_by_turn[int(check.args["turn"]) - 1])
    return reply in said, f"turn {check.args['turn']} said: {said!r}"


def _tool_ok(result: SessionResult, check: Check) -> tuple[bool, str]:
    """On candidate line ``turn`` (1-based) every call of ``tool`` answered ``ok`` (true or
    false), and there was at least one."""
    turn, tool, wanted = int(check.args["turn"]), check.args["tool"], check.args["ok"] == "true"
    calls = result.tools_by_turn[turn - 1] if turn <= len(result.tools_by_turn) else ()
    answers = [ok for name, ok in calls if name == tool]
    return bool(answers) and all(a == wanted for a in answers), (
        f"turn {turn} {tool} answered ok={answers or 'never called'} (wanted {wanted})"
    )


def _turn_failed(result: SessionResult, check: Check) -> tuple[bool, str]:
    """Candidate line ``turn`` (1-based) ended with error ``code``; ``none``: it did not fail."""
    turn, wanted = int(check.args["turn"]), check.args["code"]
    code = result.failed_by_turn[turn - 1] if turn <= len(result.failed_by_turn) else ""
    return (code or "none") == wanted, f"turn {turn} ended with {code or 'none'} (wanted {wanted})"


def _readback_assurance(result: SessionResult, check: Check) -> tuple[bool, str]:
    """The pending read-back is confirmed, and as the check says: heard, reviewed or waived."""
    pending = result.state.pending_confirmation
    if pending is None or pending.status != "confirmed":
        return False, f"no confirmed read-back ({pending.status if pending else 'none'})"
    got = assurance(pending)
    return got == check.args["assurance"], f"confirmed as {got}"


def _readback_said_whole(result: SessionResult, check: Check) -> tuple[bool, str]:
    """How many turns said the pending read-back's whole text (D39: never more than twice)."""
    pending = result.state.pending_confirmation
    text = pending.presentation_text if pending is not None else None
    times = sum(text is not None and text in " ".join(said) for said in result.spoken_by_turn)
    limit = int(check.args.get("max", "1"))
    return times <= limit, f"said whole in {times} turns (max {limit})"


def _later(stage: str) -> Callable[[SessionResult, Check], tuple[bool, str]]:
    def scorer(result: SessionResult, check: Check) -> tuple[bool, str]:
        raise NotImplementedError(f"check {check.name!r} arrives with the {stage} stage")

    return scorer


SCORERS: dict[str, Callable[[SessionResult, Check], tuple[bool, str]]] = {
    "field_equals": _field_equals,
    "field_status": _field_status,
    "brief_confirmed": _brief_confirmed,
    "brief_unconfirmed": _brief_unconfirmed,
    "outcome_is": _outcome_is,
    "lifecycle_is": _lifecycle_is,
    "no_fabricated_confirmed_values": _no_fabricated,
    "max_repeated_questions": _max_repeated_questions,
    "booking_present": _booking_present,
    "booking_absent": _booking_absent,
    "review_flag_present": _review_flag_present,
    "language_of_last_assistant_turn": _language_of_last_assistant_turn,
    "brief_language": _brief_language,
    "sources_shown_for_policy_answer": _sources_shown,
    "no_cross_store_sources": _no_cross_store_sources,
    "signal_recorded": _signal_recorded,
    "said_control_reply": _said_control_reply,
    "tool_ok": _tool_ok,
    "turn_failed": _turn_failed,
    "readback_assurance": _readback_assurance,
    "readback_said_whole": _readback_said_whole,
}
LATER: dict[str, str] = {}


# ---- helpers -------------------------------------------------------------------------------------


def _user_turn_ids(result: SessionResult) -> list[str]:
    return [t.turn_id for t in result.turns if t.role == "user"]


@cache
def _system_questions() -> frozenset[str]:
    """The fixed questions of prompts/brief.<language>.md, in every language: the brief's
    closing question, the last sentence of each read-back template and the review's check."""
    questions: set[str] = set()
    for language in get_args(Language):
        table = prompts.table("brief", language)
        questions.add(table["question"])
        questions.add(table["review.check"])  # said after each part of a review (D39)
        for key, template in table.items():
            if key.startswith("readback."):
                questions.add(template.rsplit(". ", 1)[-1])
    return frozenset(questions)


def _field(check: Check) -> CandidateFieldName:
    field = check.args["field"]
    if field not in {
        "name",
        "contact_phone",
        "interest",
        "work_authorization",
        "availability_days",
        "availability_shifts",
        "hours_per_week",
        "earliest_start_date",
        "experience",
    }:
        raise ValueError(f"unknown candidate field {field!r}")
    return field  # type: ignore[return-value]


def _parse(field: str, raw: str) -> object:
    if field in SET_FIELDS:
        return frozenset(part.strip() for part in raw.split(",") if part.strip())
    if field in INT_FIELDS:
        return int(raw)
    if field in DATE_FIELDS:
        return date.fromisoformat(raw)
    return raw
