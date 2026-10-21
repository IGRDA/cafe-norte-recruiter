"""Pure scorers over a fake run's result. Each check name maps to one function.

Checks that need retrieval, booking or the export document raise ``NotImplementedError`` with
the stage that brings them, so a scenario cannot silently pass on an unimplemented check."""

from collections import Counter
from collections.abc import Callable
from datetime import date
from functools import cache

from cafe_norte.conversation import prompts
from cafe_norte.domain.contracts import BriefTarget, CandidateFieldName, Captured, Confirmed
from cafe_norte.domain.fields import value_of
from evals.contracts import Check, CheckResult, SessionResult

CHECKS = (
    "brief_confirmed",
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
    pending = result.state.pending_confirmation
    if pending is None or not isinstance(pending.target, BriefTarget):
        return False, "no brief confirmation on record"
    current = result.state.candidate.revision
    ok = pending.status == "confirmed" and pending.target.revision == current
    return ok, f"brief {pending.status} at revision {pending.target.revision}, record at {current}"


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


def _later(stage: str) -> Callable[[SessionResult, Check], tuple[bool, str]]:
    def scorer(result: SessionResult, check: Check) -> tuple[bool, str]:
        raise NotImplementedError(f"check {check.name!r} arrives with the {stage} stage")

    return scorer


SCORERS: dict[str, Callable[[SessionResult, Check], tuple[bool, str]]] = {
    "field_equals": _field_equals,
    "field_status": _field_status,
    "brief_confirmed": _brief_confirmed,
    "outcome_is": _outcome_is,
    "lifecycle_is": _lifecycle_is,
    "no_fabricated_confirmed_values": _no_fabricated,
    "max_repeated_questions": _max_repeated_questions,
    "booking_present": _later("booking"),
    "booking_absent": _later("booking"),
    "review_flag_present": _review_flag_present,
    "language_of_last_assistant_turn": _later("language"),
    "sources_shown_for_policy_answer": _sources_shown,
    "no_cross_store_sources": _no_cross_store_sources,
}
LATER: dict[str, str] = {}


# ---- helpers -------------------------------------------------------------------------------------


@cache
def _system_questions() -> frozenset[str]:
    """The fixed questions of prompts/brief.md: the brief's closing question and the last
    sentence of each read-back template."""
    table = prompts.table("brief")
    questions = {table["question"]}
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
