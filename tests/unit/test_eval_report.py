"""The report: every number with its denominator, misses listed as misses, versions on top."""

import json
from datetime import UTC, datetime

from evals.contracts import CheckResult, Extraction, Report, RunRecord
from evals.report import render_json, render_markdown, summarize

from cafe_norte.observability.contracts import VersionStamp

VERSIONS = VersionStamp(
    config_id="chamberi_barista_v1",
    config_version="1",
    kb_version="1",
    prompt_version="ana_v15",
    schema_version="1",
    model_id="gpt-4o-mini",
    commit_sha="abc1234",
)
NOW = datetime(2026, 10, 21, 18, 0, tzinfo=UTC)


def run(
    case: str,
    model: str = "openai/gpt-4o-mini",
    *,
    ok: bool = True,
    rep: int = 1,
    failure: str = "",
    grounded: bool | None = None,
) -> RunRecord:
    checks = [CheckResult(name="brief_confirmed", ok=ok, detail="at revision 4")]
    if grounded is not None:
        checks.append(CheckResult(name="sources_shown_on_any_turn", ok=grounded, detail="d"))
        checks.append(CheckResult(name="no_cross_store_sources", ok=True, detail="d"))
    return RunRecord(
        case_id=case,
        scenario_id="S01",
        mode="live",
        model=model,
        repetition=rep,
        versions=None if failure else VERSIONS.model_copy(update={"model_id": model}),
        export=None,
        checks=() if failure else tuple(checks),
        provider_failed=False,
        estimated_cost_eur=None if failure else 0.01,
        failure=failure,
        language="es",
        extraction=None if failure else Extraction(correct=5, supplied=6, misses=("hours",)),
        tool_calls=(("update_candidate", True), ("confirm_brief", False)),
        first_text_ms=(1000, 2000, 3000),
        turn_ms=(1500, 2500, 3500),
        lines=3,
        cost_is_partial=False,
    )


def test_a_summary_per_model_counts_runs_facts_tools_and_turns() -> None:
    summary = summarize([run("C1"), run("C2", ok=False), run("C3", failure="LiveError: 422")])
    (mini,) = summary.models
    assert (mini.passed.k, mini.passed.n) == (1, 3)
    assert (mini.extraction.k, mini.extraction.n) == (10, 12)
    assert (mini.tool_calls_ok.k, mini.tool_calls_ok.n) == (3, 6)
    assert (mini.first_text.ms, mini.first_text.n) == (2000, 9)
    assert mini.cost_eur == 0.02
    assert mini.unpriced_runs == 1  # the broken run has no cost: not counted as zero


def test_grounding_counts_only_runs_that_were_checked_for_it() -> None:
    (mini,) = summarize([run("C2", grounded=True), run("C6", grounded=False), run("C1")]).models
    assert (mini.grounding.k, mini.grounding.n) == (3, 4)


def test_misses_are_listed_with_their_reason() -> None:
    summary = summarize([run("C1", ok=False, rep=2), run("C3", failure="SimulatorError: x")])
    assert summary.misses == (
        "C1 openai/gpt-4o-mini #2: brief_confirmed (at revision 4)",
        "C3 openai/gpt-4o-mini #1: SimulatorError: x",
    )


def test_two_models_are_summarized_apart_and_by_case() -> None:
    summary = summarize([run("C1"), run("C1", "openai/gpt-4o", ok=False)])
    assert [m.model for m in summary.models] == ["openai/gpt-4o-mini", "openai/gpt-4o"]
    assert [(c.case_id, c.model, c.passed.k, c.passed.n) for c in summary.cases] == [
        ("C1", "openai/gpt-4o-mini", 1, 1),
        ("C1", "openai/gpt-4o", 0, 1),
    ]
    assert [(g.config_id, g.language, g.passed.n) for g in summary.groups] == [
        ("chamberi_barista_v1", "es", 1),
        ("chamberi_barista_v1", "es", 1),
    ]


def test_markdown_shows_denominators_versions_and_misses() -> None:
    report = Report(suite="comparison", runs=(run("C1"), run("C2", ok=False)), denominators={})
    text = render_markdown(report, generated_at=NOW)
    assert "prompt `ana_v15`" in text and "commit `abc1234`" in text
    assert "1/2 (50%)" in text
    assert "10/12 (83%)" in text
    assert "2.0 s (n=6 turns)" in text
    assert "## Misses" in text and "C2 openai/gpt-4o-mini #1: brief_confirmed" in text
    assert "≥ 95 %" in text  # the target is stated next to the number, not hidden


def test_an_empty_report_says_so() -> None:
    text = render_markdown(Report(suite="scenarios", runs=(), denominators={}), generated_at=NOW)
    assert "No runs." in text


def test_json_carries_the_summary_and_no_conversation() -> None:
    report = Report(suite="comparison", runs=(run("C1"),), denominators={})
    payload = json.loads(render_json(report, generated_at=NOW))
    assert payload["summary"]["models"][0]["passed"] == {"k": 1, "n": 1}
    assert payload["runs"][0]["export"] is None
    assert "export" not in json.dumps(payload["summary"])


def test_the_report_shows_the_judges_apart_and_labels_self_judging() -> None:
    judged = run("C1").model_copy(
        update={"scores": {"goal_accuracy": 1.0, "rubric": 0.5}, "judge_model": "openai/gpt-4o"}
    )
    unscored = run("C2").model_copy(
        update={"scores": {"goal_accuracy": None}, "judge_model": "openai/gpt-4o"}
    )
    (model,) = summarize([judged, unscored]).models
    assert str(model.judged["goal_accuracy"]) == "1.00 (n=1, 1 unscored)"
    assert model.judged["style"].mean is None and not model.judge_same_model
    text = render_markdown(
        Report(suite="scenarios", runs=(judged, unscored), denominators={}), generated_at=NOW
    )
    assert "## Judges" in text and "secondary signal" in text and "| no |" in text
    itself = judged.model_copy(update={"judge_model": "openai/gpt-4o-mini"})
    assert summarize([itself]).models[0].judge_same_model


def test_a_report_without_a_judge_has_no_judge_section() -> None:
    text = render_markdown(
        Report(suite="scenarios", runs=(run("C1"),), denominators={}), generated_at=NOW
    )
    assert "judge" not in text.lower()
