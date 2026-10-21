"""Every scenario file is replayed against the real runtime with the fake model. A failing
check names the scenario and the check, so a broken conversation rule blocks the merge."""

from pathlib import Path

import pytest
import yaml
from evals.contracts import Scenario, Step
from evals.runner import load_scenarios, main, run_fake, script_events

from cafe_norte.model.contracts import ModelFinished, ModelText, ToolCall
from tests.support import ROOT

SCENARIOS = ROOT / "evals" / "cases" / "scenarios"
FILES = sorted(SCENARIOS.glob("S*.yaml"))


@pytest.mark.parametrize("path", FILES, ids=[p.stem for p in FILES])
async def test_scenario_passes_every_check(path: Path) -> None:
    scenario = Scenario.model_validate(yaml.safe_load(path.read_text()))
    record = await run_fake(scenario)
    failed = [f"{c.name}: {c.detail}" for c in record.checks if not c.ok]
    assert not failed, f"{scenario.id} {scenario.title}\n" + "\n".join(failed)
    assert record.provider_failed is False


def test_script_events_maps_steps_to_model_rounds() -> None:
    steps = (
        Step(tool="update_candidate", args={"patch": {"name": "Ane"}, "evidence_text": "Ane"}),
        Step(say="¿Te interesa?"),
    )
    rounds = script_events(steps)
    assert len(rounds) == 2
    call, finished = rounds[0]
    assert isinstance(call, ToolCall) and call.name == "update_candidate"
    assert '"name": "Ane"' in call.arguments_json
    assert finished == ModelFinished(reason="tool_calls")
    assert rounds[1] == [ModelText(text="¿Te interesa?"), ModelFinished(reason="stop")]


def test_a_step_is_a_tool_or_a_sentence_and_the_script_matches_the_lines() -> None:
    with pytest.raises(ValueError):
        Step(tool="update_candidate", say="both")
    with pytest.raises(ValueError):
        Step()
    data = yaml.safe_load((SCENARIOS / "S03.yaml").read_text())
    data["fake_script"] = data["fake_script"][:1]
    with pytest.raises(ValueError, match="one entry per scripted turn"):
        Scenario.model_validate(data)


def test_loading_filters_by_id_and_rejects_unknown_ids() -> None:
    assert [s.id for s in load_scenarios(SCENARIOS)] == [p.stem for p in FILES]
    assert [s.id for s in load_scenarios(SCENARIOS, only=["S03"])] == ["S03"]
    with pytest.raises(ValueError, match="S99"):
        load_scenarios(SCENARIOS, only=["S99"])


def test_the_cli_runs_the_fake_suite_and_reports(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--suite", "scenarios", "--mode", "fake"]) == 0
    out = capsys.readouterr().out
    assert "S01" in out and "S03" in out and "failed: 0" in out
    assert main(["--suite", "retrieval", "--retriever", "lexical"]) == 0
    assert "recall@3" in capsys.readouterr().out
    assert main(["--suite", "scenarios", "--mode", "live"]) == 2
