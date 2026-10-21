"""The rubric judge: booleans or nothing, labelled, never a pass/fail."""

from datetime import UTC, datetime
from pathlib import Path

from evals.contracts import JudgeVerdict, Report, RunRecord
from evals.judge import JUDGE_TRANSCRIPT_CHARS, judge, render_transcript
from evals.live_runs import with_judge
from evals.report import render_markdown, summarize
from evals.runner import load_scenarios

from cafe_norte.model.contracts import ModelEvent, ModelFinished, ModelText
from cafe_norte.model.fake import FakeModel
from cafe_norte.persistence.export import ExportDocument

RUBRIC = ("Ana disclosed being an AI.", "Ana asked one question at a time.")
LINES = (("assistant", "Hola, soy Ana, una IA."), ("user", "Hola."))


def said(text: str) -> list[ModelEvent]:
    return [ModelText(text=text), ModelFinished(reason="stop")]


async def verdict(text: str, *, answering: str = "gpt-4o") -> JudgeVerdict:
    model = FakeModel([said(text)])
    return await judge(model, transcript=LINES, rubric=RUBRIC, answering_model=answering)


async def test_booleans_in_order_become_answers_per_bullet() -> None:
    result = await verdict('{"answers": [true, false]}')
    assert result.answers == {RUBRIC[0]: True, RUBRIC[1]: False}
    assert result.unparsable == ""
    assert result.judge_model == "fake"


async def test_strings_that_look_like_booleans_are_not_booleans() -> None:
    result = await verdict('{"answers": ["true", false]}')
    assert result.answers == {}
    assert "boolean" in result.unparsable


async def test_a_wrong_count_or_no_json_is_unparsable() -> None:
    assert "2" in (await verdict('{"answers": [true]}')).unparsable
    assert (await verdict("Both hold.")).unparsable


async def test_a_fenced_json_block_is_accepted() -> None:
    result = await verdict('```json\n{"answers": [true, true]}\n```')
    assert all(result.answers.values())


async def test_judging_with_the_answering_model_is_flagged() -> None:
    assert (await verdict('{"answers": [true, true]}', answering="fake")).same_model
    assert not (await verdict('{"answers": [true, true]}')).same_model


def test_a_long_transcript_keeps_its_end() -> None:
    lines = tuple(("user", f"línea {n} " + "x" * 200) for n in range(200))
    text = render_transcript(lines)
    assert len(text) <= JUDGE_TRANSCRIPT_CHARS
    assert "línea 199" in text and text.startswith("[…]")


EXPORT = ExportDocument.model_validate_json(
    (Path(__file__).resolve().parents[1] / "examples" / "session_export.example.json").read_text()
)


def record(judged: JudgeVerdict | None = None) -> RunRecord:
    return RunRecord(
        case_id="S01",
        mode="live",
        model="openai/gpt-4o-mini",
        versions=EXPORT.versions,
        export=EXPORT,
        checks=(),
        judge=judged,
        provider_failed=False,
        estimated_cost_eur=0.0,
    )


async def test_a_run_is_judged_on_its_exported_transcript() -> None:
    (scenario,) = load_scenarios(only=["S01"])
    model = FakeModel([said('{"answers": [true, false]}')])
    judged = await with_judge(record(), scenario, model)
    assert judged.judge is not None
    assert judged.judge.answers == dict(zip(scenario.rubric, (True, False), strict=True))
    (messages,) = model.calls
    assert EXPORT.transcript[0].text[:30] in messages[-1].content


async def test_no_judge_or_no_rubric_leaves_the_run_alone() -> None:
    (scenario,) = load_scenarios(only=["S01"])
    assert (await with_judge(record(), scenario, None)).judge is None
    unrubric = scenario.model_copy(update={"rubric": ()})
    assert (await with_judge(record(), unrubric, FakeModel([]))).judge is None


def test_the_report_shows_the_judge_apart_and_labelled() -> None:
    held = JudgeVerdict(judge_model="gpt-4o", answers={"a": True, "b": False}, same_model=False)
    broken = JudgeVerdict(judge_model="gpt-4o", unparsable="x", same_model=False)
    report = Report(suite="scenarios", runs=(record(held), record(broken)), denominators={})
    (model,) = summarize(report.runs).models
    assert (model.judge_held.k, model.judge_held.n, model.judge_unparsable) == (1, 2, 1)
    text = render_markdown(report, generated_at=datetime(2026, 10, 21, tzinfo=UTC))
    assert "secondary signal" in text and "1/2 (50%)" in text


def test_a_report_without_a_judge_has_no_judge_section() -> None:
    report = Report(suite="scenarios", runs=(record(),), denominators={})
    text = render_markdown(report, generated_at=datetime(2026, 10, 21, tzinfo=UTC))
    assert "judge" not in text.lower()
