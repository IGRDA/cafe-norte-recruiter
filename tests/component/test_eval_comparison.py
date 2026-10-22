"""Spec §13's bounded comparison, ready to run: six cases, two models, two runs each."""

import json
from pathlib import Path

import pytest
from evals.runner import comparison_plan, main


def test_the_plan_is_six_cases_two_models_two_runs() -> None:
    plan = comparison_plan(["openai/gpt-4o-mini", "openai/gpt-4o"], repeat=2)
    assert len(plan) == 24
    assert [p.case_id for p in plan[:4]] == ["C1", "C1", "C2", "C2"]
    assert {p.model for p in plan[:12]} == {"openai/gpt-4o-mini"}  # one server per model
    assert {(p.case_id, p.scenario.id) for p in plan} >= {("C1", "S04"), ("C6", "S06")}


def test_the_comparison_prints_its_price_and_waits_for_yes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["--suite", "comparison"]) == 0
    out = capsys.readouterr().out
    assert "24 runs" in out and "Nothing was spent" in out


def test_a_free_comparison_writes_live_and_committed_results(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    committed = tmp_path / "comparison"
    args = ["--suite", "comparison", "--models", "fake", "--repeat", "1", "--simulator", "fake"]
    argv = [*args, "--max-turns", "1", "--out", str(tmp_path / "live"), "--yes"]
    code = main(argv, committed=committed)
    assert code == 1
    (json_file,) = committed.glob("*.json")
    (md_file,) = committed.glob("*.md")
    payload = json.loads(json_file.read_text())
    assert payload["summary"]["models"][0]["runs"] == 6
    assert all(run["export"] is None for run in payload["runs"])
    assert "Decision rule" in md_file.read_text()
    (live_dir,) = (tmp_path / "live").iterdir()
    assert len(list((live_dir / "exports").iterdir())) == 6
