"""The rubric judge: booleans or nothing, labelled, never a pass/fail."""

from evals.contracts import JudgeVerdict
from evals.judge import judge
from evals.live_runs import with_judge
from evals.runner import load_scenarios

from cafe_norte.model.fake import FakeModel
from tests.support.evals import EXPORT, record
from tests.support.harness import says

RUBRIC = ("Ana disclosed being an AI.", "Ana asked one question at a time.")
LINES = (("assistant", "Hola, soy Ana, una IA."), ("user", "Hola."))


async def verdict(text: str, *, answering: str = "gpt-4o") -> JudgeVerdict:
    model = FakeModel([says(text)])
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


async def test_a_run_is_judged_on_its_exported_transcript() -> None:
    (scenario,) = load_scenarios(only=["S01"])
    model = FakeModel([says('{"answers": [true, false]}')])
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
