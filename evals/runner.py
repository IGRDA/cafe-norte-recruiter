"""Load scenarios, replay them against the real runtime with the fake model, score, report;
and the CLI for every suite.

Fake mode is the CI gate: no network, no credentials, under a second per scenario. Live mode
and the comparison drive the public API with a simulated candidate (``evals/live_runs.py``,
D43) and spend only with ``--yes``; the retrieval suite runs the 41 questions."""

import argparse
import asyncio
import json
import os
from collections.abc import Sequence
from datetime import UTC, datetime, time, timedelta
from pathlib import Path

import yaml

from cafe_norte.conversation.contracts import AssistantText, TurnInput
from cafe_norte.conversation.handlers import all_handlers
from cafe_norte.conversation.prompts import PROMPT_VERSION
from cafe_norte.conversation.registry import ToolRegistry
from cafe_norte.conversation.runtime import Limits, Runtime
from cafe_norte.conversation.signals import ModelSignalAnalyzer
from cafe_norte.domain.configuration import load_configurations
from cafe_norte.domain.contracts import InputId, SessionId, SessionState
from cafe_norte.errors import ServiceError
from cafe_norte.knowledge.contracts import Index, Retriever
from cafe_norte.knowledge.fake import FakeEmbedder
from cafe_norte.knowledge.hybrid import HybridRetriever
from cafe_norte.knowledge.index import index_from_documents
from cafe_norte.knowledge.loader import load_documents
from cafe_norte.model.contracts import ModelEvent, ModelFinished, ModelText, ToolCall
from cafe_norte.model.fake import FakeModel
from cafe_norte.observability.contracts import ProcessVersions, stamp
from cafe_norte.observability.fakes import NullTelemetry
from cafe_norte.persistence.contracts import Store
from cafe_norte.persistence.export import SCHEMA_VERSION, build_export
from cafe_norte.persistence.memory import MemoryStore
from cafe_norte.persistence.seed import seed_calendar
from evals import scorecard_live
from evals.contracts import (
    ComparisonCase,
    FakeSignal,
    Fault,
    RetrievalReport,
    RunRecord,
    Scenario,
    Step,
    TurnObservation,
)
from evals.live import MAX_LIVE_TURNS
from evals.live_runs import DEFAULT_SIMULATOR, Planned, execute
from evals.observation import fold, session_result
from evals.ragas_bridge import score_with_ragas, to_ragas_samples
from evals.retrieval import load_cases, run_retrieval, write_report
from evals.scorecard import render_markdown as render_scorecard
from evals.scorecard import scorecard
from evals.scorers import run_check

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS_DIR = ROOT / "evals" / "cases" / "scenarios"
CONFIG_DIR = ROOT / "config"
KB_DIR = ROOT / "kb"
RETRIEVAL_RESULTS = ROOT / "evals" / "results" / "retrieval"
LIVE_RESULTS = ROOT / "evals" / "results" / "live"
DEFAULT_MODEL = "openai/gpt-4.1"  # what the hosted demo runs (D49)
COMPARISON_CASES = ROOT / "evals" / "cases" / "comparison" / "cases.yaml"
COMPARISON_RESULTS = ROOT / "evals" / "results" / "comparison"  # committed (.gitignore)
COMPARISON_MODELS = ("openai/gpt-4.1", "openai/gpt-4o-mini")  # hosted and previous (D49)
COMPARISON_REPEAT = 2
SCORECARD_JUDGE = "openai/gpt-4o-mini"  # D51: the ragas judges' model

_FAKE_INDEX: dict[str, Index] = {}


async def fake_retriever(kb_version: str) -> Retriever:
    """The real hybrid retriever over the real KB with deterministic fake vectors: fusion and
    filtering are exercised in CI; the numbers mean nothing."""
    if kb_version not in _FAKE_INDEX:
        _FAKE_INDEX[kb_version] = await index_from_documents(
            load_documents(KB_DIR), FakeEmbedder(), kb_version=kb_version
        )
    return HybridRetriever(_FAKE_INDEX[kb_version], FakeEmbedder())


def load_scenarios(directory: Path = SCENARIOS_DIR, only: Sequence[str] = ()) -> list[Scenario]:
    scenarios = [
        Scenario.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        for path in sorted(directory.glob("S*.yaml"))
    ]
    if only:
        known = {s.id for s in scenarios}
        missing = sorted(set(only) - known)
        if missing:
            raise ValueError(f"no scenario {', '.join(missing)} in {directory}")
        scenarios = [s for s in scenarios if s.id in set(only)]
    return scenarios


def script_events(steps: Sequence[Step]) -> list[list[ModelEvent]]:
    """One model round per step: a tool step is the call plus ``tool_calls``; a say step is the
    sentence plus ``stop``. ``say: ""`` is a turn the system finishes by itself (a read-back)."""
    rounds: list[list[ModelEvent]] = []
    for index, step in enumerate(steps):
        if step.tool is not None:
            call = ToolCall(
                call_id=f"s{index}",
                name=step.tool,
                arguments_json=json.dumps(step.args, ensure_ascii=False, default=str),
            )
            rounds.append([call, ModelFinished(reason="tool_calls")])
        else:
            rounds.append([ModelText(text=step.say or ""), ModelFinished(reason="stop")])
    return rounds


def signal_analyzer(verdicts: Sequence[FakeSignal]) -> ModelSignalAnalyzer | None:
    """The real classifier adapter over a fake model that answers each line's verdict."""
    if not verdicts:
        return None
    scripts: list[list[ModelEvent]] = [
        [ModelText(text=verdict.model_dump_json()), ModelFinished(reason="stop")]
        for verdict in verdicts
    ]
    return ModelSignalAnalyzer(FakeModel(scripts))


async def run_fake(scenario: Scenario, store: Store | None = None) -> RunRecord:
    """Replay the scenario: open the session, one turn per candidate line, then the checks.
    ``store`` defaults to a fresh memory store; a test may pass an opened Postgres one."""
    clock_at = datetime.combine(datetime.fromisoformat(scenario.today), time(10, 0), tzinfo=UTC)
    store = store if store is not None else MemoryStore(clock=lambda: clock_at)
    configurations = load_configurations(CONFIG_DIR)
    configuration = configurations[scenario.config_id]
    await seed_calendar(store, configurations, now=clock_at)
    scripts = [round_ for steps in scenario.fake_script for round_ in script_events(steps)]
    model = FakeModel(scripts)
    retriever = await fake_retriever(configuration.kb_version)
    now = [clock_at]  # the runtime's clock: each turn moves it by ``seconds_per_turn``
    runtime = Runtime(
        model=model,
        tools=ToolRegistry(
            all_handlers(store=store, configurations=configurations, retriever=retriever)
        ),
        store=store,
        configurations=configurations,
        signals=signal_analyzer(scenario.fake_signals),
        limits=Limits(),
        telemetry=NullTelemetry(),
        owner="evals",
        clock=lambda: now[0],
    )
    faults = {fault.turn: fault for fault in scenario.faults}
    expected_failures = {int(c.args["turn"]) for c in scenario.checks if c.name == "turn_failed"}
    process = ProcessVersions(
        model_id=model.model_id,
        prompt_version=PROMPT_VERSION,
        schema_version=SCHEMA_VERSION,
        commit_sha="local",
    )
    session_id = SessionId(f"eval-{scenario.id}")
    await store.sessions.create(
        SessionState(
            session_id=session_id,
            config_id=configuration.config_id,
            config_version=configuration.version,
            language=scenario.language,
            channel="text",
            created_at=clock_at,
        ),
        access_hash="",
    )
    observations: list[TurnObservation] = []
    surprises: list[str] = []
    async for _ in runtime.open_session(session_id):
        pass
    for index, line in enumerate(scenario.scripted_turns):
        number = index + 1
        received_at = now[0]
        now[0] = received_at + timedelta(seconds=scenario.seconds_per_turn)
        turn = TurnInput(
            session_id=session_id,
            input_id=InputId(f"in-{index}"),
            text=line,
            channel="text",
            received_at=received_at,
        )
        fault = faults.get(number)
        _arm(fault, model, store)
        observation = TurnObservation()
        stream = runtime.run_turn(turn)
        async for event in stream:
            observation = fold(observation, event)
            if fault is not None and fault.kind == "interrupt" and isinstance(event, AssistantText):
                if len(observation.spoken) >= fault.after_sentences:
                    break  # the candidate speaks over Ana
        await stream.aclose()
        if fault is not None and fault.kind == "interrupt":
            await runtime.delivered(
                observation.turn_id, text=" ".join(observation.spoken), complete=False
            )
        if observation.failed and number not in expected_failures:
            surprises.append(f"turn {number}: {observation.failed}")
        await runtime.settle()
        observations.append(observation)

    state = await store.sessions.get(session_id)
    assert state is not None
    versions = stamp(configuration, process)
    snapshot = await store.snapshot(session_id, versions=versions, taken_at=clock_at)
    assert snapshot is not None
    export = build_export(snapshot)
    result = session_result(
        state,
        await store.turns.recent(session_id, 1000),
        observations,
        allowed_doc_ids=configuration.kb_doc_ids,
        signals=export.signals,
    )
    checks = tuple(run_check(result, check) for check in scenario.checks)
    return RunRecord(
        case_id=scenario.id,
        mode="fake",
        versions=versions,
        export=export,
        checks=checks,
        provider_failed=bool(surprises),
        estimated_cost_eur=0.0,
        scenario_id=scenario.id,
        model=model.model_id,
        language=scenario.language,
        lines=len(scenario.scripted_turns),
        cost_is_partial=False,
    )


def _arm(fault: Fault | None, model: FakeModel, store: Store) -> None:
    """Make the fault happen on its turn: the next model call or the next session save fails."""
    if fault is None:
        return
    if fault.kind == "model":
        model.fail_next()
    elif fault.kind == "storage":
        if not isinstance(store, MemoryStore):
            raise ValueError("a storage fault needs the memory store")
        store.sessions.fail_next_save = ServiceError("scripted outage", code="provider_unavailable")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evals")
    parser.add_argument(
        "--suite",
        choices=["scenarios", "retrieval", "comparison", "scorecard"],
        default="scenarios",
    )
    parser.add_argument("--mode", choices=["fake", "live"], default="fake")
    parser.add_argument("--only", nargs="*", default=[])
    parser.add_argument("--repeat", type=int, default=None, help="scenarios 1, comparison 2")
    parser.add_argument("--models", nargs="*", default=[])
    parser.add_argument(
        "--judge",
        default=None,
        help=f"provider/model, fake or off; default off, the scorecard's {SCORECARD_JUDGE}",
    )
    parser.add_argument("--retriever", choices=["hybrid", "lexical"], default="hybrid")
    parser.add_argument("--out", default=None, help="results directory (per suite default)")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--ragas", action="store_true", help="retrieval: add ragas' ID metrics")
    parser.add_argument(
        "--save-baseline", action="store_true", help="scorecard: commit this run as the baseline"
    )
    live = parser.add_argument_group("live runs (paid; the estimate is printed first)")
    live.add_argument("--model", default=os.environ.get("CAFE_NORTE_MODEL") or DEFAULT_MODEL)
    live.add_argument("--simulator", default=DEFAULT_SIMULATOR)
    live.add_argument(
        "--base-url", default=None, help="an existing server; access code from EVAL_ACCESS_CODE"
    )
    live.add_argument("--max-turns", type=int, default=MAX_LIVE_TURNS)
    live.add_argument("--langfuse", action="store_true", help="sync cases and runs (needs keys)")
    live.add_argument("--yes", action="store_true", help="spend: without it nothing is called")
    args = parser.parse_args(argv)

    if args.list:
        for scenario in load_scenarios():
            print(f"{scenario.id}  {scenario.title}")
        return 0
    if args.suite == "retrieval":
        out = Path(args.out or RETRIEVAL_RESULTS)
        return retrieval_main(args.retriever, args.only, out, ragas=args.ragas)
    if args.suite == "scorecard":
        return scorecard_main(args)
    if args.suite == "scenarios" and args.mode == "live":
        return live_main(args)
    if args.suite == "comparison":
        return comparison_main(args)
    if args.suite != "scenarios" or args.mode != "fake":
        print(f"{args.suite} in {args.mode} mode is not available yet (later stage).")
        return 2
    try:
        scenarios = load_scenarios(only=args.only)
    except ValueError as error:
        print(error)
        return 1
    failed = 0
    for scenario in scenarios:
        record = asyncio.run(run_fake(scenario))
        bad = [c for c in record.checks if not c.ok]
        status = "ok  " if not bad and not record.provider_failed else "FAIL"
        print(f"{status} {scenario.id}  {scenario.title}  ({len(record.checks)} checks)")
        for check in bad:
            print(f"       - {check.name}: {check.detail}")
        if record.provider_failed:
            print("       - a turn failed")
        failed += bool(bad or record.provider_failed)
    print(f"scenarios: {len(scenarios)}  failed: {failed}  prompt: {PROMPT_VERSION}")
    return 1 if failed else 0


def live_main(args: argparse.Namespace) -> int:
    """Scenarios with ``live_checks``, the simulated candidate, the chosen model."""
    try:
        scenarios = load_scenarios(only=args.only)
    except ValueError as error:
        print(error)
        return 1
    not_live = [s.id for s in scenarios if not s.live_checks]
    if not_live:
        print(f"no live_checks, not run live: {', '.join(not_live)}")
        return 2
    plan = [
        Planned(case_id=s.id, scenario=s, model=args.model, repetition=r)
        for s in scenarios
        for r in range(1, (args.repeat or 1) + 1)
    ]
    return execute(
        plan,
        suite="scenarios",
        simulator=args.simulator,
        base_url=args.base_url,
        access_code=os.environ.get("EVAL_ACCESS_CODE") or None,
        max_turns=args.max_turns,
        out=Path(args.out or LIVE_RESULTS),
        yes=args.yes,
        judge=None if args.judge in (None, "off") else args.judge,
        langfuse=args.langfuse,
    )


def comparison_plan(models: Sequence[str], *, repeat: int) -> list[Planned]:
    """Every comparison case, ``repeat`` times, for each model in turn (one server each)."""
    cases = [ComparisonCase.model_validate(c) for c in yaml.safe_load(COMPARISON_CASES.read_text())]
    scenarios = {s.id: s for s in load_scenarios(only=[c.scenario_id for c in cases])}
    return [
        Planned(
            case_id=case.id,
            scenario=scenarios[case.scenario_id],
            model=model,
            repetition=r,
            emphasis=case.emphasis,
        )
        for model in models
        for case in cases
        for r in range(1, repeat + 1)
    ]


def comparison_main(args: argparse.Namespace) -> int:
    """Spec §13: the six cases through each model, ``COMPARISON_REPEAT`` times, on loopback."""
    plan = comparison_plan(
        args.models or COMPARISON_MODELS, repeat=args.repeat or COMPARISON_REPEAT
    )
    return execute(
        plan,
        suite="comparison",
        simulator=args.simulator,
        base_url=None,
        access_code=None,
        max_turns=args.max_turns,
        out=Path(args.out or LIVE_RESULTS),
        yes=args.yes,
        judge=None if args.judge in (None, "off") else args.judge,
        langfuse=args.langfuse,
        committed=COMPARISON_RESULTS,
    )


def retrieval_report(
    mode: str, only: Sequence[str] = (), *, ragas: bool = False
) -> RetrievalReport:
    """The fixture's questions through the real retriever: ``hybrid`` needs the knowledge extra
    and downloads the model once; ``lexical`` is BM25 only and runs anywhere. ``ragas`` adds its
    ID-based context precision and recall over the answerable questions (offline, free)."""
    configurations = load_configurations(CONFIG_DIR)
    (kb_version,) = {c.kb_version for c in configurations.values()}
    documents = load_documents(KB_DIR)
    if mode == "hybrid":
        from cafe_norte.knowledge.embedder import FastEmbedEmbedder

        embedder: FastEmbedEmbedder | None = FastEmbedEmbedder()
    else:
        embedder = None
    index = asyncio.run(index_from_documents(documents, embedder, kb_version=kb_version))
    retriever = HybridRetriever(index, embedder)
    cases = [c for c in load_cases() if not only or c.id in set(only)]
    report = asyncio.run(run_retrieval(cases, retriever, configurations))
    if ragas:
        scores = asyncio.run(score_with_ragas(to_ragas_samples(report.runs, cases)))
        report = report.model_copy(update={"ragas": scores})
    return report


def retrieval_main(mode: str, only: Sequence[str], out: Path, *, ragas: bool = False) -> int:
    report = retrieval_report(mode, only, ragas=ragas)
    path = write_report(report, out)
    for run in report.runs:
        mark = {True: "hit ", False: "MISS", None: "    "}[run.hit] + (
            " LEAK" if run.leaked else ""
        )
        print(f"{mark} {run.case_id} {run.kind:<11} {run.milliseconds:>4} ms  {list(run.returned)}")
    print(
        f"recall@3 {report.recall_at_3:.0%} (n={report.answerable})  leaked {report.leaked}/"
        f"{len(report.runs)}  unsupported with sources {report.unsupported_with_sources}/"
        f"{sum(r.kind == 'unsupported' for r in report.runs)}  "
        f"median {report.median_ms} ms  {report.embedding_model}  -> {path}"
    )
    if report.ragas is not None:
        precision = report.ragas.mean_precision
        print(
            f"ragas id-based: precision {'–' if precision is None else f'{precision:.2f}'} "
            f"(n={report.ragas.samples - report.ragas.nothing_retrieved}), recall "
            f"{report.ragas.mean_recall:.2f} (n={report.ragas.samples})"
        )
    return 0 if report.leaked == 0 else 1


def scorecard_main(args: argparse.Namespace) -> int:
    """Fake: tiers 0 and 1 over every fake scenario and the retrieval fixture, free and offline,
    the numbers ``make check`` gates on. Live: the scenarios with ``live_checks`` and every
    knowledge-base question as a probe against ``--model``, judged by ragas (D51)."""
    retrieval = retrieval_report(args.retriever, ragas=True)
    if args.mode == "live":
        scenarios = [s for s in load_scenarios(only=args.only) if s.live_checks]
        return scorecard_live.execute(
            scenarios,
            load_cases(),
            retrieval,
            model=args.model,
            simulator=args.simulator,
            judge=args.judge or SCORECARD_JUDGE,
            base_url=args.base_url,
            access_code=os.environ.get("EVAL_ACCESS_CODE") or None,
            max_turns=args.max_turns,
            out=Path(args.out or LIVE_RESULTS),
            yes=args.yes,
            save_baseline=args.save_baseline,
            langfuse=args.langfuse,
        )
    scenarios = load_scenarios(only=args.only)
    runs = [asyncio.run(run_fake(s)) for s in scenarios]
    target = scorecard_live.BASELINES / "offline.json"  # the fake scenarios, not a live model
    card = scorecard(
        runs,
        {s.id: s for s in scenarios},
        retrieval=retrieval,
        baseline=scorecard_live.load_baseline(target),
    )
    print(render_scorecard(card))
    if args.save_baseline:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(card.model_dump_json(indent=2) + "\n")
        print(f"baseline -> {target}")
    return 1 if card.gate_failures else 0
