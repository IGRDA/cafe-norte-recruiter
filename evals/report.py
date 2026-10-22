"""Markdown and JSON reports with explicit denominators.

``summarize`` is pure: runs in, one ``ModelSummary`` per answering model out, every rate a
``Ratio`` (k of n) and every latency a ``Median`` with its n. A run that broke counts in the
denominator of everything it could have passed and is listed under misses with its reason."""

import statistics
from collections.abc import Callable, Iterable, Sequence
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from evals.contracts import Report, RunRecord

GROUNDING_CHECKS = frozenset(
    {"sources_shown_on_any_turn", "sources_shown_for_policy_answer", "no_cross_store_sources"}
)
EXTRACTION_TARGET = 0.95  # spec §13: exact normalized supplied facts


_DECISION = [
    "## Decision rule",
    "",
    "Same prompt, tools, KB and configuration for every model (spec §13). Prefer the cheaper "
    "or faster model only if it preserves the required correctness: runs passed, extraction "
    "target, no fabricated field and grounding at least as good as the other model's. The "
    "owner decides and records the decision in docs/DECISIONS.md.",
    "",
]


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Ratio(Frozen):
    k: int
    n: int

    def __str__(self) -> str:
        return f"{self.k}/{self.n} ({round(100 * self.k / self.n)}%)" if self.n else "0/0 (–)"


class Median(Frozen):
    ms: int | None
    n: int

    def __str__(self) -> str:
        return f"{self.ms / 1000:.1f} s (n={self.n} turns)" if self.ms is not None else "– (n=0)"


class Score(Frozen):
    mean: float | None
    n: int  # runs scored
    missing: int  # runs the judge was asked about and gave no score

    def __str__(self) -> str:
        shown = "–" if self.mean is None else f"{self.mean:.2f}"
        return f"{shown} (n={self.n}{f', {self.missing} unscored' if self.missing else ''})"


JUDGED = ("goal_accuracy", "rubric", "style", "topic_adherence")  # D48, report only


class ModelSummary(Frozen):
    model: str
    runs: int
    passed: Ratio  # runs that passed every live check and did not break
    extraction: Ratio  # persona facts held exactly, over facts supplied
    fabrication_free: Ratio  # runs whose no_fabricated_confirmed_values check held
    tool_calls_ok: Ratio
    grounding: Ratio  # grounding checks that held, over those evaluated
    first_text: Median  # runner's clock, POST to first sentence
    turn_total: Median  # runner's clock, POST to the turn's end
    cost_eur: float  # the answering model, priced runs only
    unpriced_runs: int  # runs with no cost or a partial one
    turn_cap_runs: int
    judged: dict[str, Score]  # scorecard row id -> the judge's mean over the runs it scored
    judge_same_model: bool  # some run was judged by its own answering model


class CaseRow(Frozen):
    case_id: str
    model: str
    passed: Ratio


class GroupRow(Frozen):
    config_id: str
    language: str
    model: str
    passed: Ratio


class Summary(Frozen):
    models: tuple[ModelSummary, ...]
    cases: tuple[CaseRow, ...]
    groups: tuple[GroupRow, ...]  # spec §13: by configuration and language
    misses: tuple[str, ...]


def summarize(runs: Sequence[RunRecord]) -> Summary:
    return Summary(
        models=tuple(_model(model, rs) for model, rs in _by(runs, lambda r: r.model)),
        cases=tuple(
            CaseRow(case_id=case, model=model, passed=_passed(rs))
            for (case, model), rs in _by(runs, lambda r: (r.case_id, r.model))
        ),
        groups=tuple(
            GroupRow(config_id=config, language=language, model=model, passed=_passed(rs))
            for (config, language, model), rs in _by(
                runs, lambda r: (_config(r), r.language or "?", r.model)
            )
        ),
        misses=tuple(_miss(r) for r in runs if not r.passed),
    )


def render_markdown(report: Report, *, generated_at: datetime) -> str:
    summary = summarize(report.runs)
    lines = [f"# Evaluation report · {report.suite}", "", _header(report, generated_at), ""]
    if not report.runs:
        return "\n".join([*lines, "No runs.", ""])
    lines += [
        "| Model | Runs passed | Extraction (exact facts) | No fabricated field | Tool calls ok "
        "| Grounding checks | First sentence, median | Turn, median | Cost (answering model) |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for m in summary.models:
        cost = f"€{m.cost_eur:.3f}" + (
            f" ({m.unpriced_runs} runs unpriced)" if m.unpriced_runs else ""
        )
        lines.append(
            f"| `{m.model}` | {m.passed} | {m.extraction} | {m.fabrication_free} | "
            f"{m.tool_calls_ok} | {m.grounding} | {m.first_text} | {m.turn_total} | {cost} |"
        )
    lines += [
        "",
        f"Targets (spec §13): extraction ≥ {round(EXTRACTION_TARGET * 100)} % exact on supplied "
        "facts and zero fabricated confirmed fields. A miss of either is a miss, whatever the "
        "other numbers say. Latency is the runner's clock over HTTP, not the voice path. "
        "Samples are small: no number here is a production percentile.",
        "",
        *(_DECISION if report.suite == "comparison" else []),
        *_judge_section(report.runs, summary),
        "## By configuration and language",
        "",
        "| Configuration | Language | Model | Runs passed |",
        "| --- | --- | --- | --- |",
        *(f"| {g.config_id} | {g.language} | `{g.model}` | {g.passed} |" for g in summary.groups),
        "",
        "## By case",
        "",
        "| Case | Model | Runs passed |",
        "| --- | --- | --- |",
        *(f"| {c.case_id} | `{c.model}` | {c.passed} |" for c in summary.cases),
        "",
        "## Misses",
        "",
        *([f"- {miss}" for miss in summary.misses] or ["None."]),
        "",
    ]
    return "\n".join(lines)


class ReportFile(Frozen):
    """``report.json``: the summary and every run without its export (exports hold
    conversations and live next to it, ignored by git)."""

    generated_at: datetime
    suite: Literal["scenarios", "retrieval", "comparison"]
    denominators: dict[str, int]
    summary: Summary
    runs: tuple[RunRecord, ...]


def render_json(report: Report, *, generated_at: datetime) -> str:
    return (
        ReportFile(
            generated_at=generated_at,
            suite=report.suite,
            denominators=report.denominators,
            summary=summarize(report.runs),
            runs=tuple(run.model_copy(update={"export": None}) for run in report.runs),
        ).model_dump_json(indent=2)
        + "\n"
    )


# ---- helpers -------------------------------------------------------------------------------------


def _model(model: str, runs: Sequence[RunRecord]) -> ModelSummary:
    extraction = [r.extraction for r in runs if r.extraction is not None]
    fabricated = [c for r in runs for c in r.checks if c.name == "no_fabricated_confirmed_values"]
    grounding = [c for r in runs for c in r.checks if c.name in GROUNDING_CHECKS]
    tools = [ok for r in runs for _, ok in r.tool_calls]
    priced = [r for r in runs if r.estimated_cost_eur is not None and not r.cost_is_partial]
    return ModelSummary(
        model=model,
        runs=len(runs),
        passed=_passed(runs),
        extraction=Ratio(
            k=sum(e.correct for e in extraction), n=sum(e.supplied for e in extraction)
        ),
        fabrication_free=Ratio(k=sum(c.ok for c in fabricated), n=len(fabricated)),
        tool_calls_ok=Ratio(k=sum(tools), n=len(tools)),
        grounding=Ratio(k=sum(c.ok for c in grounding), n=len(grounding)),
        first_text=_median(ms for r in runs for ms in r.first_text_ms),
        turn_total=_median(ms for r in runs for ms in r.turn_ms),
        cost_eur=round(sum(r.estimated_cost_eur or 0.0 for r in priced), 6),
        unpriced_runs=len(runs) - len(priced),
        turn_cap_runs=sum(r.hit_turn_cap for r in runs),
        judged={key: _score(runs, key) for key in JUDGED},
        judge_same_model=any(r.judge_model == r.model for r in runs if r.judge_model),
    )


def _score(runs: Sequence[RunRecord], key: str) -> Score:
    asked = [r.scores[key] for r in runs if key in r.scores]
    given = [v for v in asked if v is not None]
    return Score(
        mean=statistics.fmean(given) if given else None,
        n=len(given),
        missing=len(asked) - len(given),
    )


def _judge_section(runs: Sequence[RunRecord], summary: Summary) -> list[str]:
    judges = sorted({r.judge_model for r in runs if r.judge_model})
    if not judges:
        return []
    rows = [
        f"| `{m.model}` | {' | '.join(str(m.judged[k]) for k in JUDGED)} | "
        f"{'yes: biased' if m.judge_same_model else 'no'} |"
        for m in summary.models
    ]
    return [
        "## Judges",
        "",
        f"A secondary signal, never pass/fail (D06, D48); ragas over `{', '.join(judges)}`. "
        "Each a mean of pass (1) or fail (0) per run; the rubric, the share of its bullets held.",
        "",
        "| Model | Goal achieved | Rubric bullets | Style | On topic "
        "| Judge is the answering model |",
        "| --- | --- | --- | --- | --- | --- |",
        *rows,
        "",
    ]


def _passed(runs: Sequence[RunRecord]) -> Ratio:
    return Ratio(k=sum(r.passed for r in runs), n=len(runs))


def _median(values: Iterable[int]) -> Median:
    found = list(values)
    return Median(ms=round(statistics.median(found)) if found else None, n=len(found))


def _miss(run: RunRecord) -> str:
    where = f"{run.case_id} {run.model} #{run.repetition}"
    if run.failure:
        return f"{where}: {run.failure}"
    failed = [f"{c.name} ({c.detail})" for c in run.checks if not c.ok]
    if run.provider_failed:
        failed.append("a turn failed")
    return f"{where}: {'; '.join(failed)}"


def _config(run: RunRecord) -> str:
    return run.versions.config_id if run.versions is not None else "?"


def _by[K](
    runs: Sequence[RunRecord], key: Callable[[RunRecord], K]
) -> list[tuple[K, list[RunRecord]]]:
    """Groups in order of first appearance."""
    groups: dict[K, list[RunRecord]] = {}
    for run in runs:
        groups.setdefault(key(run), []).append(run)
    return list(groups.items())


def _header(report: Report, generated_at: datetime) -> str:
    first = next((r.versions for r in report.runs if r.versions is not None), None)
    when = generated_at.strftime("%Y-%m-%d %H:%M UTC")
    if first is None:
        return f"Generated {when}."
    return (
        f"Generated {when} · prompt `{first.prompt_version}` · KB `{first.kb_version}` · "
        f"schema `{first.schema_version}` · commit `{first.commit_sha}` · "
        f"{len(report.runs)} runs."
    )
