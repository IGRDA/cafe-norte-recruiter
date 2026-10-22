"""Live runs from plan to results: which server, which candidate, what is recorded and where.

A plan is a list of (case, scenario, model, repetition). Runs are grouped by model so the
loopback target builds one app per model (``serve``); ``--base-url`` points every run at an
existing server instead (hosted, or ``make run``). Nothing here runs until the caller has
printed the spend estimate and the owner passed ``--yes``."""

import asyncio
import os
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from itertools import groupby
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict

from cafe_norte.domain.configuration import load_configurations
from cafe_norte.errors import ServiceError
from cafe_norte.main import create_default_app
from cafe_norte.model.contracts import Model, ModelFinished, ModelText
from cafe_norte.model.fake import FakeModel
from cafe_norte.model.select import model_from_env
from cafe_norte.observability.cost import load_prices
from evals.contracts import Candidate, Report, RunRecord, Scenario
from evals.langfuse_sync import SdkSink, dataset_name, keys_present, sync
from evals.live import (
    MAX_LIVE_TURNS,
    HttpConversation,
    LiveError,
    ScriptedCandidate,
    drive,
    serve,
)
from evals.pool import CONCURRENCY, bounded
from evals.ragas_bridge import judge_from, judge_runs
from evals.report import render_json, render_markdown
from evals.scorers import checks_for, extraction_accuracy, run_check
from evals.simulator import ModelCandidateSimulator, SimulatedCandidate, SimulatorError
from evals.spend import estimate_spend

ROOT = Path(__file__).resolve().parents[1]
HTTP_TIMEOUT = httpx.Timeout(30.0, read=60.0)  # reads outlast the 15 s SSE heartbeat
DEFAULT_SIMULATOR = "openai/gpt-4o-mini"


class Planned(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    scenario: Scenario
    model: str  # the answering model's selector
    repetition: int
    emphasis: str = ""  # comparison: what the case stresses


def loopback_env(env: Mapping[str, str], model: str) -> dict[str, str]:
    """The app a loopback run serves: the given model, the memory store, text only, no access
    code, and its traces (when Langfuse keys are set) tagged ``evaluation``."""
    return {
        **env,
        "CAFE_NORTE_MODEL": model,
        "CAFE_NORTE_DATABASE_URL": "",
        "CAFE_NORTE_ACCESS_CODE": "",
        "CAFE_NORTE_VOICE": "off",
        "CAFE_NORTE_ENVIRONMENT": "evaluation",
    }


def simulator_model(selector: str, env: Mapping[str, str]) -> Model:
    """``fake`` answers "Sí." to everything, so a free run exercises the whole loop."""
    if selector == "fake":
        return FakeModel([], fallback=(ModelText(text="Sí."), ModelFinished(reason="stop")))
    return model_from_env(selector, env)


async def run_live(
    scenario: Scenario,
    conversation: HttpConversation,
    candidate: Candidate,
    *,
    model: str,
    repetition: int,
    max_turns: int,
    case_id: str = "",
) -> RunRecord:
    """Drive one session and score it with the scenario's ``live_checks``. A run that breaks
    (refused request, silent simulator, provider error) is recorded with its reason."""
    base = {
        "case_id": case_id or scenario.id,
        "scenario_id": scenario.id,
        "mode": "live",
        "model": model,
        "language": scenario.language,
        "repetition": repetition,
    }
    try:
        finished = await drive(conversation, candidate, max_turns=max_turns)
    except (LiveError, SimulatorError, ServiceError, httpx.HTTPError) as error:
        return RunRecord(
            **base,
            versions=None,
            export=None,
            checks=(),
            provider_failed=False,
            estimated_cost_eur=None,
            failure=f"{type(error).__name__}: {error}",
        )
    turns = finished.observations[1:]
    base["session_id"] = conversation.session_id
    export = finished.export
    return RunRecord(
        **base,
        versions=export.versions,
        export=export,
        checks=tuple(
            run_check(finished.result, check) for check in checks_for(scenario.live_checks)
        ),
        provider_failed=any(t.failed for t in turns),
        estimated_cost_eur=export.metrics.estimated_marginal_cost_eur,
        extraction=extraction_accuracy(scenario.persona, finished.result.state),
        tool_calls=tuple(call for t in turns for call in t.tools),
        first_text_ms=tuple(t.client_first_text_ms for t in turns if t.client_first_text_ms),
        turn_ms=tuple(t.client_total_ms for t in turns if t.client_total_ms is not None),
        lines=len(turns),
        # read from the turns: finish() has already ended the session the export shows
        hit_turn_cap=len(turns) >= max_turns
        and all(t.lifecycle in (None, "active") for t in turns),
        cost_is_partial=export.metrics.cost_is_partial,
    )


async def run_plan(
    plan: Sequence[Planned],
    *,
    simulator: str,
    base_url: str | None,
    access_code: str | None,
    max_turns: int = MAX_LIVE_TURNS,
    judge: str | None = None,
    env: Mapping[str, str] | None = None,
    concurrency: int = CONCURRENCY,
) -> list[RunRecord]:
    """Every planned run, grouped by model (one server each); within a model, ``concurrency``
    sessions at a time. Records come back in plan order."""
    env = env if env is not None else os.environ
    configurations = load_configurations(ROOT / "config")
    voice = ModelCandidateSimulator(simulator_model(simulator, env))
    answer_judge = judge_from(judge) if judge else None
    records: list[RunRecord] = []
    for model, runs in groupby(plan, key=lambda p: p.model):
        async with target(model, base_url, env) as url:

            async def one(planned: Planned, url: str = url, model: str = model) -> RunRecord:
                scenario = planned.scenario
                async with httpx.AsyncClient(base_url=url, timeout=HTTP_TIMEOUT) as client:
                    conversation = HttpConversation(
                        client,
                        config_id=scenario.config_id,
                        language=scenario.language,
                        allowed_doc_ids=configurations[scenario.config_id].kb_doc_ids,
                        access_code=access_code if base_url else None,
                    )
                    candidate: Candidate = (
                        ScriptedCandidate(scenario.scripted_turns)
                        if scenario.live_candidate == "scripted"
                        else SimulatedCandidate(voice, scenario.persona, scenario.language)
                    )
                    record = await run_live(
                        scenario,
                        conversation,
                        candidate,
                        model=model,
                        repetition=planned.repetition,
                        max_turns=max_turns,
                        case_id=planned.case_id,
                    )
                print(_line(record), flush=True)
                return record

            records += await bounded(list(runs), one, limit=concurrency)
    if answer_judge is None:
        return records
    scenarios = {p.scenario.id: p.scenario for p in plan}
    return await judge_runs(records, scenarios, answer_judge, concurrency=concurrency)


def write_results(report: Report, out: Path, *, now: datetime | None = None) -> Path:
    """``<out>/<UTC time>-<suite>/``: ``report.md``, ``report.json`` (no conversations) and
    every export in ``exports/``. Ignored by git: exports hold conversations."""
    now = now or datetime.now(UTC)
    directory = out / f"{now.strftime('%Y%m%dT%H%M%SZ')}-{report.suite}"
    (directory / "exports").mkdir(parents=True)
    (directory / "report.md").write_text(render_markdown(report, generated_at=now), "utf-8")
    (directory / "report.json").write_text(render_json(report, generated_at=now), "utf-8")
    many_models = len({run.model for run in report.runs}) > 1
    for run in report.runs:
        if run.export is not None:
            model = f"{run.model.replace('/', '_')}-" if many_models else ""
            name = f"{run.case_id}-{model}{run.repetition}.json"
            (directory / "exports" / name).write_text(
                run.export.model_dump_json(indent=2) + "\n", encoding="utf-8"
            )
    return directory


def write_committed(report: Report, directory: Path, *, now: datetime) -> Path:
    """``<date>-<prompt version>.md`` and ``.json`` with no conversation in either: the
    comparison's structured results, kept in the repository (spec §13)."""
    directory.mkdir(parents=True, exist_ok=True)
    prompt = next((r.versions.prompt_version for r in report.runs if r.versions), "unknown")
    stem = directory / f"{now.strftime('%Y-%m-%d')}-{prompt}"
    stem.with_suffix(".md").write_text(render_markdown(report, generated_at=now), "utf-8")
    stem.with_suffix(".json").write_text(render_json(report, generated_at=now), "utf-8")
    return stem.with_suffix(".json")


def _line(record: RunRecord) -> str:
    status = "ok  " if record.passed else "MISS"
    extraction = (
        f"facts {record.extraction.correct}/{record.extraction.supplied}"
        if record.extraction
        else "facts -"
    )
    detail = record.failure or ", ".join(c.name for c in record.checks if not c.ok) or ""
    return (
        f"{status} {record.case_id} {record.model} #{record.repetition}  {extraction}  "
        f"lines {record.lines}  {detail}"
    ).rstrip()


@asynccontextmanager
async def target(model: str, base_url: str | None, env: Mapping[str, str]) -> AsyncIterator[str]:
    if base_url:
        yield base_url
        return
    async with serve(create_default_app(loopback_env(env, model))) as url:
        yield url


def execute(
    plan: Sequence[Planned],
    *,
    suite: Literal["scenarios", "comparison"],
    simulator: str,
    base_url: str | None,
    access_code: str | None,
    max_turns: int,
    out: Path,
    yes: bool,
    judge: str | None = None,
    committed: Path | None = None,
    langfuse: bool = False,
) -> int:
    """Print what the plan will cost; without ``yes`` stop there. Otherwise run it, write the
    results, and exit 0 only when every run passed."""
    spend = estimate_spend(
        [p.model for p in plan], simulator=simulator, judge=judge, prices=load_prices()
    )
    print(spend.describe())
    if not yes:
        print("Nothing was spent. Add --yes to run it.")
        return 0
    records = asyncio.run(
        run_plan(
            plan,
            simulator=simulator,
            base_url=base_url,
            access_code=access_code,
            max_turns=max_turns,
            judge=judge,
        )
    )
    passed = sum(r.passed for r in records)
    report = Report(
        suite=suite, runs=tuple(records), denominators={"runs": len(records), "passed": passed}
    )
    now = datetime.now(UTC)
    path = write_results(report, out, now=now)
    print(f"{suite}: {passed}/{len(records)} passed  -> {path}")
    if committed is not None:
        print(f"results to commit -> {write_committed(report, committed, now=now)}")
    if langfuse:
        if keys_present():
            sync(report, plan, SdkSink.from_env())
            print(f"Langfuse: dataset {dataset_name(suite)}, {len(records)} runs as experiments")
        else:
            print("Langfuse: skipped, LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are not set")
    return 0 if passed == len(records) else 1
