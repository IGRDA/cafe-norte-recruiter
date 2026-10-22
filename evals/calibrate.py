"""Judge calibration (D51): the pass/fail judges against labelled conversations.

A judge row is only worth reading if the judge agrees with a person on clear cases. Each case
in ``cases/judge/calibration.yaml`` names a criterion (topic, style, goal) and the verdict a
correct judge gives; this prints the agreement per criterion and every miss with the judge's
reason. A wording or a judge model is kept only at full agreement.

    python -m evals.calibrate --judge openai/gpt-4o-mini          # prints the estimate only
    python -m evals.calibrate --judge openai/gpt-4o-mini --yes
"""

import argparse
import asyncio
from collections.abc import Sequence
from pathlib import Path

import yaml

from cafe_norte.observability.cost import load_prices
from evals.contracts import AnswerJudge, CalibrationCase
from evals.ragas_bridge import GOAL, STYLE, TOPIC, judge_from
from evals.spend import estimate_calls

CASES = Path(__file__).parent / "cases" / "judge" / "calibration.yaml"
TOKENS_PER_CASE = (3_000, 400)  # a numeric metric makes two or three calls


def load_calibration(path: Path = CASES) -> list[CalibrationCase]:
    return [CalibrationCase.model_validate(c) for c in yaml.safe_load(path.read_text())]


def criterion(case: CalibrationCase) -> str:
    match case.criterion:
        case "topic":
            return TOPIC
        case "style":
            return STYLE
        case _:
            return GOAL.format(goal=case.goal)


async def verdict(judge: AnswerJudge, case: CalibrationCase) -> tuple[bool, str]:
    """Pass or fail as the scorecard would read it: a numeric score passes at 0.5 or more."""
    match case.criterion:
        case "faithfulness":
            score = await judge.faithfulness(case.question, case.answer, case.contexts)
            return score >= 0.5, f"score {score:.2f}"
        case "accuracy":
            score = await judge.answer_accuracy(case.question, case.answer, case.reference)
            return score >= 0.5, f"score {score:.2f}"
        case _:
            held = await judge.holds(case.conversation, criterion(case))
            return held, getattr(judge, "last_reason", "")


async def calibrate(
    judge: AnswerJudge, cases: Sequence[CalibrationCase]
) -> list[tuple[CalibrationCase, bool | None, str]]:
    """Each case with the judge's verdict (``None``: it gave none) and its reason, if any."""
    found: list[tuple[CalibrationCase, bool | None, str]] = []
    for case in cases:
        try:
            held: bool | None
            held, reason = await verdict(judge, case)
        except Exception as error:  # a judge's failure is a miss, whatever it was
            held, reason = None, f"{type(error).__name__}: {error}"
        found.append((case, held, reason))
    return found


def render(found: Sequence[tuple[CalibrationCase, bool | None, str]]) -> str:
    lines: list[str] = []
    for name in ("faithfulness", "accuracy", "topic", "style", "goal"):
        rows = [(c, h, r) for c, h, r in found if c.criterion == name]
        right = sum(h is not None and h == (c.expected == "pass") for c, h, _ in rows)
        lines.append(f"{name:<12} {right}/{len(rows)}")
        lines += [
            f"   MISS {c.id}: expected {c.expected}, judged "
            f"{'none' if h is None else 'pass' if h else 'fail'} · {r[:160]}"
            for c, h, r in rows
            if h is None or h != (c.expected == "pass")
        ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evals.calibrate")
    parser.add_argument("--judge", default="openai/gpt-4o-mini")
    parser.add_argument("--yes", action="store_true", help="spend: without it nothing is called")
    args = parser.parse_args(argv)
    cases = load_calibration()
    spend = estimate_calls(
        [(args.judge, TOKENS_PER_CASE, len(cases))],
        load_prices(),
        runs=len(cases),
        basis=f"{len(cases)} labelled cases, one judge call each",
    )
    print(spend.describe())
    judge = judge_from(args.judge) if args.yes else None  # building it needs the key
    if judge is None:
        print("Nothing was spent. Add --yes to run it.")
        return 0
    found = asyncio.run(calibrate(judge, cases))
    print(render(found))
    return 0 if all(h is not None and h == (c.expected == "pass") for c, h, _ in found) else 1


if __name__ == "__main__":
    raise SystemExit(main())
