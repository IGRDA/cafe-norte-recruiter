"""A live scenario run from target to record, without spending: the loopback app with the
scripted model, a scripted candidate, and the CLI's spend guard."""

import json
from pathlib import Path

import httpx
import pytest
from evals.contracts import Check
from evals.live import HttpConversation, ScriptedCandidate, serve
from evals.live_runs import loopback_env, run_live
from evals.runner import load_scenarios, main, script_events

from cafe_norte.domain.contracts import ConfigId
from cafe_norte.model.fake import FakeModel
from tests.support import build_test_app


def test_the_loopback_app_gets_the_model_a_memory_store_and_no_gate() -> None:
    env = loopback_env(
        {
            "CAFE_NORTE_DATABASE_URL": "postgresql://x",
            "CAFE_NORTE_ACCESS_CODE": "secret",
            "CAFE_NORTE_VOICE": "pipecat",
            "OPENAI_API_KEY": "k",
        },
        "openai/gpt-4o",
    )
    assert env["CAFE_NORTE_MODEL"] == "openai/gpt-4o"
    assert env["CAFE_NORTE_DATABASE_URL"] == ""
    assert env["CAFE_NORTE_ACCESS_CODE"] == ""
    assert env["CAFE_NORTE_VOICE"] == "off"
    assert env["CAFE_NORTE_ENVIRONMENT"] == "evaluation"
    assert env["OPENAI_API_KEY"] == "k"


async def test_a_live_run_records_checks_extraction_tools_and_timings() -> None:
    (scenario,) = load_scenarios(only=["S03"])
    scenario = scenario.model_copy(
        update={"live_checks": (Check(name="outcome_is", args={"outcome": "not_interested"}),)}
    )
    scripts = [r for steps in scenario.fake_script for r in script_events(steps)]
    async with (
        serve(build_test_app(model=FakeModel(scripts))) as base_url,
        httpx.AsyncClient(base_url=base_url) as client,
    ):
        conversation = HttpConversation(
            client,
            config_id=ConfigId(scenario.config_id),
            language=scenario.language,
            allowed_doc_ids=frozenset(),
        )
        record = await run_live(
            scenario,
            conversation,
            ScriptedCandidate(scenario.scripted_turns),
            model="fake",
            repetition=1,
            max_turns=10,
        )
    assert record.mode == "live"
    assert record.passed
    assert [c.name for c in record.checks] == ["outcome_is"]
    assert record.tool_calls == (("update_candidate", True), ("end_session", True))
    assert len(record.turn_ms) == 2 and len(record.first_text_ms) == 2
    assert record.extraction is not None and record.extraction.supplied == 0
    assert record.lines == 2 and not record.hit_turn_cap
    assert record.versions is not None and record.export is not None


async def test_a_run_that_breaks_is_a_recorded_miss_not_a_crash() -> None:
    (scenario,) = load_scenarios(only=["S01"])
    async with (
        serve(build_test_app(model=FakeModel([]))) as base_url,
        httpx.AsyncClient(base_url=base_url) as client,
    ):
        conversation = HttpConversation(
            client, config_id=ConfigId("nope"), language="es", allowed_doc_ids=frozenset()
        )
        record = await run_live(
            scenario, conversation, ScriptedCandidate(()), model="fake", repetition=1, max_turns=1
        )
    assert not record.passed
    assert "422" in record.failure or "404" in record.failure


def test_live_mode_prints_the_estimate_and_spends_nothing_without_yes(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    code = main(["--suite", "scenarios", "--mode", "live", "--only", "S01", "--out", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 0
    assert "estimated spend" in out and "--yes" in out
    assert not list(tmp_path.iterdir())


def test_a_scenario_without_live_checks_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--suite", "scenarios", "--mode", "live", "--only", "S03"]) == 2
    assert "S03" in capsys.readouterr().out


def test_a_free_live_run_writes_its_report(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """The whole path on the fake model and simulator: nothing to pass, everything recorded."""
    code = main(
        [
            "--suite", "scenarios", "--mode", "live", "--only", "S01",
            "--model", "fake", "--simulator", "fake", "--max-turns", "2",
            "--out", str(tmp_path), "--yes",
        ]
    )  # fmt: skip
    assert code == 1  # the demo model cannot pass S01
    (run_dir,) = tmp_path.iterdir()
    report = json.loads((run_dir / "report.json").read_text())
    assert report["suite"] == "scenarios"
    assert report["runs"][0]["case_id"] == "S01"
    assert (run_dir / "exports" / "S01-1.json").exists()
    assert "S01" in capsys.readouterr().out
