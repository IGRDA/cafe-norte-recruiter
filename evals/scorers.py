"""Pure scorers over the export document. Each check name maps to one function."""

from cafe_norte.persistence.export import ExportDocument
from evals.contracts import Check, CheckResult

CHECKS = (
    "brief_confirmed",
    "booking_present",
    "booking_absent",
    "field_equals",
    "field_status",
    "no_fabricated_confirmed_values",
    "review_flag_present",
    "outcome_is",
    "language_of_last_assistant_turn",
    "sources_shown_for_policy_answer",
    "no_cross_store_sources",
    "max_repeated_questions",
)


def run_check(export: ExportDocument, check: Check) -> CheckResult:
    raise NotImplementedError
