"""Judge calibration: labelled cases, the agreement per criterion, every miss named."""

import pytest
from evals.calibrate import calibrate, criterion, load_calibration, main, render
from evals.ragas_bridge import GOAL, STYLE, TOPIC, FakeAnswerJudge


def test_every_criterion_has_cases_on_both_sides() -> None:
    cases = load_calibration()
    for name in ("faithfulness", "accuracy", "topic", "style", "goal"):
        verdicts = {c.expected for c in cases if c.criterion == name}
        assert verdicts == {"pass", "fail"}, name
    goal = next(c for c in cases if c.criterion == "goal")
    assert criterion(goal) == GOAL.format(goal=goal.goal)
    assert {criterion(c) for c in cases if c.criterion in ("topic", "style")} == {TOPIC, STYLE}


async def test_a_judge_that_passes_everything_misses_every_fail_case() -> None:
    cases = load_calibration()
    found = await calibrate(FakeAnswerJudge(1.0), cases)
    text = render(found)
    fails = [c.id for c in cases if c.expected == "fail"]
    assert all(f"MISS {case}" in text for case in fails)
    assert "topic        2/4" in text


class Broken(FakeAnswerJudge):
    async def holds(self, exchanges: object, criterion: str) -> bool:
        raise TimeoutError("judge timed out")


async def test_a_judge_that_fails_is_a_miss_with_its_reason() -> None:
    (case,) = [c for c in load_calibration() if c.id == "topic-answers-the-job"]
    ((_, held, reason),) = await calibrate(Broken(), [case])
    assert held is None and reason == "TimeoutError: judge timed out"


def test_nothing_is_spent_without_yes(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--judge", "openai/gpt-4o"]) == 0
    out = capsys.readouterr().out
    assert "estimated spend" in out and "Nothing was spent" in out
