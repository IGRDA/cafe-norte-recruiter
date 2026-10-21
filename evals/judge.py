"""Rubric judge through the ``Model`` port: one JSON boolean per bullet, or no answer.

A secondary signal (D06): it never decides a run, the report shows it apart from the checks,
and a judge that is also the answering model is flagged. Anything but a JSON list of exactly
one real boolean per bullet is recorded as unparsable, never coerced."""

import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from functools import cache
from pathlib import Path

from cafe_norte.model.contracts import Model, ModelMessage, ModelText
from evals.contracts import JudgeVerdict
from evals.spend import model_id

PROMPT = Path(__file__).with_name("prompts") / "judge.md"
JUDGE_SECONDS = 60.0
JUDGE_TRANSCRIPT_CHARS = 12_000  # the newest part is kept; the start is marked as cut


async def judge(
    model: Model,
    *,
    transcript: Sequence[tuple[str, str]],
    rubric: Sequence[str],
    answering_model: str,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> JudgeVerdict:
    """``transcript``: (role, text) with role ``user`` or ``assistant``, as exported."""
    statements = "\n".join(f"{n}. {bullet}" for n, bullet in enumerate(rubric, start=1))
    messages = (
        ModelMessage(role="system", content=_prompt()),
        ModelMessage(
            role="user",
            content=f"Rubric:\n{statements}\n\nTranscript:\n{render_transcript(transcript)}",
        ),
    )
    deadline = clock() + timedelta(seconds=JUDGE_SECONDS)
    text = "".join(
        [
            event.text
            async for event in model.stream(messages, (), deadline=deadline)
            if isinstance(event, ModelText)
        ]
    )
    same = model.model_id == model_id(answering_model)
    answers, problem = _parse(text, len(rubric))
    if problem:
        return JudgeVerdict(judge_model=model.model_id, unparsable=problem, same_model=same)
    return JudgeVerdict(
        judge_model=model.model_id, answers=dict(zip(rubric, answers, strict=True)), same_model=same
    )


def render_transcript(lines: Sequence[tuple[str, str]]) -> str:
    text = "\n".join(f"{'Ana' if role == 'assistant' else 'Candidate'}: {t}" for role, t in lines)
    if len(text) <= JUDGE_TRANSCRIPT_CHARS:
        return text
    return "[…]" + text[-(JUDGE_TRANSCRIPT_CHARS - len("[…]")) :]


def _parse(text: str, expected: int) -> tuple[list[bool], str]:
    body = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        answers = json.loads(body)["answers"]
    except (ValueError, KeyError, TypeError):
        return [], f"not the JSON object asked for: {text[:80]!r}"
    if not isinstance(answers, list) or not all(type(a) is bool for a in answers):
        return [], "answers are not all JSON booleans"
    if len(answers) != expected:
        return [], f"{len(answers)} answers for {expected} statements"
    return answers, ""


@cache
def _prompt() -> str:
    return PROMPT.read_text(encoding="utf-8")
