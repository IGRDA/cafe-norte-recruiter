"""The live fixtures hold together: every live run has checks the scorers know, and the
comparison only points at scenarios that can run live."""

import yaml
from evals.contracts import ComparisonCase
from evals.runner import load_scenarios
from evals.scorers import SCORERS

from tests.support import ROOT

COMPARISON = ROOT / "evals" / "cases" / "comparison" / "cases.yaml"
RELEASE_GATE = {"S01", "S02"}  # spec §13: both live happy paths must complete


def comparison_cases() -> list[ComparisonCase]:
    return [ComparisonCase.model_validate(c) for c in yaml.safe_load(COMPARISON.read_text())]


def test_every_live_check_is_a_scorer_with_no_turn_number() -> None:
    for scenario in load_scenarios():
        for check in scenario.live_checks:
            assert check.name in SCORERS, f"{scenario.id}: {check.name}"
            assert "turn" not in check.args, f"{scenario.id}: {check.name} names a turn"


def test_the_release_gate_and_the_comparison_can_run_live() -> None:
    live = {s.id for s in load_scenarios() if s.live_checks}
    needed = RELEASE_GATE | {c.scenario_id for c in comparison_cases()}
    assert needed <= live, f"no live_checks: {sorted(needed - live)}"


def test_a_corrected_fact_starts_from_another_value() -> None:
    """The simulator says the first value and corrects it later; the same value twice would
    be no correction at all."""
    for scenario in load_scenarios():
        for field, value in scenario.persona.corrections:
            assert scenario.persona.facts.get(field) != value, scenario.id
