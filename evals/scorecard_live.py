"""The live scorecard (D48): every scenario with ``live_checks`` and every knowledge-base
question as a probe, against one answering model; then ragas over both, the offline retrieval
suite, and one scorecard with its delta against the committed baseline.

Nothing runs before the estimate is printed and ``--yes`` was passed. Results go to
``results/live/<UTC>-scorecard/`` (ignored): ``scorecard.md``, ``scorecard.json`` and
``probes.json`` (no exports). ``--save-baseline`` commits the scorecard as
``results/scorecard/<model>.json``."""

import asyncio
import os
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from pydantic import TypeAdapter

from cafe_norte.observability.cost import load_prices
from evals.contracts import (
    ProbeRecord,
    Report,
    RetrievalCase,
    RetrievalReport,
    RunRecord,
    Scenario,
    Scorecard,
)
from evals.langfuse_sync import (
    RAG_DATASET,
    SdkSink,
    keys_present,
    probe_run,
    sync,
    sync_rag_dataset,
)
from evals.live_runs import Planned, run_plan
from evals.probes import run_probes
from evals.ragas_bridge import judge_from, judge_probes, judge_runs
from evals.scorecard import render_markdown, scorecard
from evals.spend import estimate_scorecard

ROOT = Path(__file__).resolve().parents[1]
BASELINES = ROOT / "evals" / "results" / "scorecard"  # committed (.gitignore)


def baseline_path(model: str) -> Path:
    """``openai/gpt-4o-mini`` → ``results/scorecard/openai-gpt-4o-mini.json``."""
    return BASELINES / f"{model.replace('/', '-')}.json"


def load_baseline(path: Path) -> Scorecard | None:
    return Scorecard.model_validate_json(path.read_text()) if path.exists() else None


def execute(
    scenarios: Sequence[Scenario],
    cases: Sequence[RetrievalCase],
    retrieval: RetrievalReport | None,
    *,
    model: str,
    simulator: str,
    judge: str,
    base_url: str | None,
    access_code: str | None,
    max_turns: int,
    out: Path,
    yes: bool,
    save_baseline: bool = False,
    langfuse: bool = False,
) -> int:
    """Print the estimate; without ``yes`` stop there. Otherwise run, score, write, and exit 1
    when a gated row missed its target."""
    spend = estimate_scorecard(
        model,
        scenarios=len(scenarios),
        probes=len(cases),
        simulator=simulator,
        judge=None if judge in ("off", "fake") else judge,
        prices=load_prices(),
    )
    print(spend.describe())
    if not yes:
        print("Nothing was spent. Add --yes to run it.")
        return 0
    plan = [Planned(case_id=s.id, scenario=s, model=model, repetition=1) for s in scenarios]
    runs, probes = asyncio.run(
        _run(
            plan,
            cases,
            model=model,
            simulator=simulator,
            judge=judge,
            base_url=base_url,
            access_code=access_code,
            max_turns=max_turns,
        )
    )
    by_id = {s.id: s for s in scenarios}
    target = baseline_path(model)
    card = scorecard(
        runs, by_id, probes=probes, retrieval=retrieval, model=model, baseline=load_baseline(target)
    )
    markdown = render_markdown(card)
    print(markdown)
    folder = out / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-scorecard"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "scorecard.md").write_text(markdown, encoding="utf-8")
    (folder / "scorecard.json").write_text(card.model_dump_json(indent=2) + "\n")
    bare = [p.model_copy(update={"run": p.run.model_copy(update={"export": None})}) for p in probes]
    (folder / "probes.json").write_bytes(
        TypeAdapter(list[ProbeRecord]).dump_json(bare, indent=2) + b"\n"
    )
    print(f"results -> {folder}")
    if save_baseline:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(card.model_dump_json(indent=2) + "\n")
        print(f"baseline -> {target}")
    if langfuse:
        _sync(runs, plan, probes, cases, model)
    return 1 if card.gate_failures else 0


async def _run(
    plan: Sequence[Planned],
    cases: Sequence[RetrievalCase],
    *,
    model: str,
    simulator: str,
    judge: str,
    base_url: str | None,
    access_code: str | None,
    max_turns: int,
) -> tuple[list[RunRecord], list[ProbeRecord]]:
    runs = await run_plan(
        plan, simulator=simulator, base_url=base_url, access_code=access_code, max_turns=max_turns
    )
    probes = await run_probes(
        cases, model=model, base_url=base_url, access_code=access_code, env=os.environ
    )
    answer_judge = judge_from(judge)
    probes = await judge_probes(probes, cases, answer_judge)
    if answer_judge is not None:
        runs = await judge_runs(runs, {p.scenario.id: p.scenario for p in plan}, answer_judge)
    return runs, probes


def _sync(
    runs: Sequence[RunRecord],
    plan: Sequence[Planned],
    probes: Sequence[ProbeRecord],
    cases: Sequence[RetrievalCase],
    model: str,
) -> None:
    if not keys_present():
        print("Langfuse: skipped, LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are not set")
        return
    sink = SdkSink.from_env()
    sync(Report(suite="scenarios", runs=tuple(runs), denominators={}), plan, sink)
    sync_rag_dataset(cases, sink)
    sink.record_run(RAG_DATASET, probe_run(probes, model))
    print(f"Langfuse: {len(runs)} scenario runs and {len(probes)} probes as experiments")
