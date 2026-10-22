"""Everything ragas measures for us (D43, D51).

Retrieval: the fixture's expected sections are chunk ids, so ragas' ID-based context
precision and recall apply exactly, offline, with no model. Probes: ``ToolCallF1`` on the tool
names a question's turn called, also offline. Judges: ``RagasJudge`` implements the
``AnswerJudge`` port with ragas' ``Faithfulness``, ``AnswerAccuracy`` and a pass/fail
``DiscreteMetric`` over an OpenAI model, which reads every criterion: staying on topic, the
goal, the style and the rubric bullets. ragas' ``TopicAdherence`` and
``AgentGoalAccuracyWithReference`` misjudged plain Spanish exchanges on gpt-4o-mini and gpt-4o
(D51). ``FakeAnswerJudge`` stands in, free. ragas is imported where it is used: it takes
seconds and only these need it. A judge that fails leaves no score, never a guessed one."""

import asyncio
import math
import re
import warnings
from collections.abc import Awaitable, Mapping, Sequence
from pathlib import Path
from typing import Any

from evals.contracts import (
    AnswerJudge,
    Exchange,
    ProbeRecord,
    RagasCaseScore,
    RagasSample,
    RagasScores,
    RetrievalCase,
    RetrievalRun,
    RunRecord,
    Scenario,
)
from evals.scorers import exchanges, model_turns

_SENTENCE = re.compile(r"(?<=[.!?])\s+")
JUDGE_SECONDS = 90.0  # one metric on one sample; past it the sample has no score
CRITERION_PROMPT = Path(__file__).parent / "prompts" / "criterion.md"
# The fixed criteria. A wording is kept only when the judge agrees with every labelled case in
# ``cases/judge/calibration.yaml`` (``python -m evals.calibrate``, D51).
TOPIC = (
    "Ana does not answer anything outside the barista job, the store, the candidate's details "
    "and the interview: no jokes, opinions or unrelated tasks."
)
STYLE = (
    "Ana speaks to the candidate informally, as is normal in Spain: tú forms such as te, tu, "
    "puedes or ¿cómo te llamas? are correct. Fail only if Ana uses usted, le or su for the "
    "candidate. English turns are correct."
)
GOAL = (
    "Every part of this goal is achieved by the end of the conversation, judged from what Ana "
    "says and the tools she calls; one part that fails fails the whole: {goal}"
)


def to_ragas_samples(
    runs: Sequence[RetrievalRun], cases: Sequence[RetrievalCase]
) -> list[RagasSample]:
    by_id = {c.id: c for c in cases}
    return [
        RagasSample(
            case_id=run.case_id,
            user_input=by_id[run.case_id].question,
            retrieved_context_ids=run.returned,
            reference_context_ids=by_id[run.case_id].expected_sections,
        )
        for run in runs
        if by_id[run.case_id].kind == "answerable"
    ]


async def score_with_ragas(samples: Sequence[RagasSample]) -> RagasScores:
    """ragas is imported here, not at module load: it takes seconds and only this needs it."""
    from ragas import SingleTurnSample

    with warnings.catch_warnings():
        # ragas 0.4 deprecates this path for one with no ID-based precision yet.
        warnings.simplefilter("ignore", DeprecationWarning)
        from ragas.metrics import IDBasedContextPrecision, IDBasedContextRecall

    precision_metric, recall_metric = IDBasedContextPrecision(), IDBasedContextRecall()
    scores: list[RagasCaseScore] = []
    for sample in samples:
        ragas_sample = SingleTurnSample(
            user_input=sample.user_input,
            retrieved_context_ids=list(sample.retrieved_context_ids),
            reference_context_ids=list(sample.reference_context_ids),
        )
        precision = float(await precision_metric.single_turn_ascore(ragas_sample))
        recall = float(await recall_metric.single_turn_ascore(ragas_sample))
        scores.append(
            RagasCaseScore(
                case_id=sample.case_id,
                precision=None if math.isnan(precision) else precision,
                recall=recall,
            )
        )
    precisions = [s.precision for s in scores if s.precision is not None]
    return RagasScores(
        samples=len(scores),
        mean_precision=sum(precisions) / len(precisions) if precisions else None,
        mean_recall=sum(s.recall for s in scores) / len(scores) if scores else 0.0,
        nothing_retrieved=len(scores) - len(precisions),
        per_case=tuple(scores),
    )


# ---- probes: tool calls, offline -----------------------------------------------------------------

PROBE_TOOLS = ("search_knowledge",)  # every probe's question is the knowledge base's to answer


async def tool_call_f1(question: str, answer: str, called: Sequence[str]) -> float:
    """ragas ``ToolCallF1`` on tool names (arguments are the model's own wording, so they are
    not compared): one search is right; a search plus an unasked follow-up is 0.67."""
    from ragas.messages import AIMessage, HumanMessage, ToolCall
    from ragas.metrics.collections import ToolCallF1

    result = await ToolCallF1().ascore(
        user_input=[
            HumanMessage(content=question),
            AIMessage(content=answer, tool_calls=[ToolCall(name=n, args={}) for n in called]),
        ],
        reference_tool_calls=[ToolCall(name=n, args={}) for n in PROBE_TOOLS],
    )
    return _number(result.value)


# ---- judges --------------------------------------------------------------------------------------


async def judge_probes(
    probes: Sequence[ProbeRecord], cases: Sequence[RetrievalCase], judge: AnswerJudge | None
) -> list[ProbeRecord]:
    """Each probe with its scores: ``probe_tool_f1`` always (free); with a judge,
    ``faithfulness`` (answerable, sources shown), ``answer_accuracy`` (answerable) and
    ``topic_adherence``. A broken probe gets none. The answer is judged without Ana's
    follow-up question: a question is not a claim."""
    by_id = {c.id: c for c in cases}
    scored: list[ProbeRecord] = []
    for probe in probes:
        export = probe.run.export
        if export is None:
            scored.append(probe)
            continue
        case = by_id[probe.case_id]
        scores: dict[str, float | None] = {
            "probe_tool_f1": await tool_call_f1(case.question, probe.answer, probe.tools)
        }
        if judge is not None and probe.answer.strip():  # no words, nothing to judge: facts miss it
            said = claims(probe.answer)
            if case.kind == "answerable" and probe.contexts and said:
                scores["faithfulness"] = await _safely(
                    judge.faithfulness(case.question, said, probe.contexts)
                )
            if case.kind == "answerable" and case.reference:
                scores["answer_accuracy"] = await _safely(
                    judge.answer_accuracy(case.question, said, case.reference)
                )
            scores["topic_adherence"] = await _held(judge.holds(exchanges(export), TOPIC))
        scored.append(probe.model_copy(update={"scores": scores}))
    return scored


async def judge_runs(
    runs: Sequence[RunRecord], scenarios: Mapping[str, Scenario], judge: AnswerJudge
) -> list[RunRecord]:
    """Each scenario run with ``goal_accuracy`` (scenarios with a ``goal``), ``rubric`` (the
    share of its bullets that held), ``style`` and ``topic_adherence``."""
    scored: list[RunRecord] = []
    for run in runs:
        if run.export is None:
            scored.append(run)
            continue
        scenario = scenarios[run.scenario_id or run.case_id]
        said = exchanges(run.export)
        scores: dict[str, float | None] = {"topic_adherence": await _held(judge.holds(said, TOPIC))}
        if model_turns(run.export.transcript):
            scores["style"] = await _held(judge.holds(said, STYLE))
        if scenario.goal:
            goal = GOAL.format(goal=scenario.goal)
            scores["goal_accuracy"] = await _held(judge.holds(said, goal))
        if scenario.rubric:
            held = [await _held(judge.holds(said, bullet)) for bullet in scenario.rubric]
            answered = [h for h in held if h is not None]
            scores["rubric"] = sum(answered) / len(answered) if answered else None
        scored.append(run.model_copy(update={"scores": scores, "judge_model": judge.model_id}))
    return scored


class RagasJudge:
    """ragas' metrics over an OpenAI model, ``openai/<model>``; reads ``OPENAI_API_KEY``."""

    def __init__(self, selector: str) -> None:
        provider, _, model = selector.partition("/")
        if provider != "openai" or not model:
            raise ValueError(f"the ragas judge runs on openai/<model>, not {selector!r}")
        from openai import AsyncOpenAI
        from ragas.llms import llm_factory

        self._selector = selector
        self._llm = llm_factory(model, client=AsyncOpenAI())
        self.last_reason = ""

    @property
    def model_id(self) -> str:
        return self._selector

    async def faithfulness(self, question: str, answer: str, contexts: Sequence[str]) -> float:
        from ragas.metrics.collections import Faithfulness

        result = await Faithfulness(llm=self._llm).ascore(
            user_input=question, response=answer, retrieved_contexts=list(contexts)
        )
        return _number(result.value)

    async def answer_accuracy(self, question: str, answer: str, reference: str) -> float:
        """NVIDIA's answer accuracy: 0, 0.5 or 1 from two ratings against the reference. Extra
        details from the knowledge base are not counted against the answer, as
        ``FactualCorrectness`` counted them (D51)."""
        from ragas.metrics.collections import AnswerAccuracy

        result = await AnswerAccuracy(llm=self._llm).ascore(
            user_input=question, response=answer, reference=reference
        )
        return _number(result.value)

    async def holds(self, exchanges: Sequence[Exchange], criterion: str) -> bool:
        from ragas.metrics import DiscreteMetric

        metric = DiscreteMetric(
            name="criterion",
            allowed_values=["pass", "fail"],
            prompt=CRITERION_PROMPT.read_text(encoding="utf-8"),
        )
        result = await metric.ascore(
            llm=self._llm, conversation=_render(exchanges), criterion=criterion
        )
        self.last_reason = str(result.reason or "")  # for calibration's misses
        if result.value not in ("pass", "fail"):
            raise ValueError(f"criterion answered {result.value!r}")
        return bool(result.value == "pass")


class FakeAnswerJudge:
    """Free and fixed: every judge says ``score`` (``holds``: ``score >= 0.5``), so a dry run
    exercises the whole path and a test can set what the judge thinks."""

    def __init__(self, score: float = 1.0) -> None:
        self._score = score

    @property
    def model_id(self) -> str:
        return "fake"

    async def faithfulness(self, question: str, answer: str, contexts: Sequence[str]) -> float:
        return self._score

    async def answer_accuracy(self, question: str, answer: str, reference: str) -> float:
        return self._score

    async def holds(self, exchanges: Sequence[Exchange], criterion: str) -> bool:
        return self._score >= 0.5


def claims(answer: str) -> str:
    """The answer without its questions: Ana ends most turns asking the next thing."""
    return " ".join(s for s in _SENTENCE.split(answer.strip()) if s and not s.endswith("?"))


def judge_from(selector: str) -> AnswerJudge | None:
    """``off``: no judge; ``fake``: the free one; ``openai/<model>``: ragas over it."""
    if selector == "off":
        return None
    return FakeAnswerJudge() if selector == "fake" else RagasJudge(selector)


async def _safely(score: Awaitable[float]) -> float | None:
    try:
        async with asyncio.timeout(JUDGE_SECONDS):
            return await score
    except Exception as error:  # a judge's failure is a missing score, whatever it was
        print(f"judge: no score ({type(error).__name__}: {error})"[:200], flush=True)
        return None


async def _held(verdict: Awaitable[bool]) -> float | None:
    async def as_number() -> float:
        return 1.0 if await verdict else 0.0

    return await _safely(as_number())


def _number(value: Any) -> float:
    if not isinstance(value, int | float) or math.isnan(value):
        raise ValueError(f"no score: {value!r}")
    return float(value)


def _render(exchanges: Sequence[Exchange]) -> str:
    """One line per turn; the tools a turn called on a line of their own, so a judge reading
    Ana's words does not take them for something she said."""
    lines: list[str] = []
    for speaker, text, tools in exchanges:
        if tools:
            lines.append(f"(system) Ana's tools this turn: {', '.join(tools)}")
        lines.append(f"{'Candidate' if speaker == 'human' else 'Ana'}: {text}")
    return "\n".join(lines)
