"""Load scenarios, replay them against the real runtime with the fake model, score, report.

Fake mode is the CI gate: no network, no credentials, under a second per scenario. Live mode,
the retrieval and comparison suites, the judge and the simulator arrive with their stages."""

import argparse
import asyncio
import json
from collections.abc import Sequence
from datetime import UTC, datetime, time
from pathlib import Path

import yaml

from cafe_norte.conversation.contracts import AssistantText, SourcesShown, TurnFailed, TurnInput
from cafe_norte.conversation.handlers import all_handlers
from cafe_norte.conversation.prompts import PROMPT_VERSION
from cafe_norte.conversation.registry import ToolRegistry
from cafe_norte.conversation.runtime import Limits, Runtime
from cafe_norte.conversation.signals import ModelSignalAnalyzer
from cafe_norte.domain.configuration import load_configurations
from cafe_norte.domain.contracts import InputId, SessionId, SessionState
from cafe_norte.knowledge.contracts import Index, Retriever
from cafe_norte.knowledge.fake import FakeEmbedder
from cafe_norte.knowledge.hybrid import HybridRetriever
from cafe_norte.knowledge.index import index_from_documents
from cafe_norte.knowledge.loader import load_documents
from cafe_norte.model.contracts import ModelEvent, ModelFinished, ModelText, ToolCall
from cafe_norte.model.fake import FakeModel
from cafe_norte.observability.contracts import ProcessVersions, stamp
from cafe_norte.persistence.export import SCHEMA_VERSION, build_export
from cafe_norte.persistence.memory import MemoryStore
from evals.contracts import FakeSignal, RunRecord, Scenario, SessionResult, Step
from evals.retrieval import load_cases, run_retrieval, write_report
from evals.scorers import run_check

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS_DIR = ROOT / "evals" / "cases" / "scenarios"
CONFIG_DIR = ROOT / "config"
KB_DIR = ROOT / "kb"

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


async def run_fake(scenario: Scenario) -> RunRecord:
    """Replay the scenario: open the session, one turn per candidate line, then the checks."""
    store = MemoryStore()
    configurations = load_configurations(CONFIG_DIR)
    configuration = configurations[scenario.config_id]
    clock_at = datetime.combine(datetime.fromisoformat(scenario.today), time(10, 0), tzinfo=UTC)
    scripts = [round_ for steps in scenario.fake_script for round_ in script_events(steps)]
    model = FakeModel(scripts)
    retriever = await fake_retriever(configuration.kb_version)
    runtime = Runtime(
        model=model,
        tools=ToolRegistry(
            all_handlers(store=store, configurations=configurations, retriever=retriever)
        ),
        store=store,
        configurations=configurations,
        signals=signal_analyzer(scenario.fake_signals),
        limits=Limits(),
        owner="evals",
        clock=lambda: clock_at,
    )
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
    spoken_by_turn: list[tuple[str, ...]] = []
    sources_by_turn: list[tuple[str, ...]] = []
    failed_turns: list[str] = []
    async for _ in runtime.open_session(session_id):
        pass
    for index, line in enumerate(scenario.scripted_turns):
        turn = TurnInput(
            session_id=session_id,
            input_id=InputId(f"in-{index}"),
            text=line,
            channel="text",
            received_at=clock_at,
        )
        spoken: list[str] = []
        sources: list[str] = []
        async for event in runtime.run_turn(turn):
            if isinstance(event, AssistantText):
                spoken.append(event.text)
            elif isinstance(event, SourcesShown):
                sources.extend(event.chunk_ids)
            elif isinstance(event, TurnFailed):
                failed_turns.append(f"turn {index + 1}: {event.code}")
        await runtime.settle()
        spoken_by_turn.append(tuple(spoken))
        sources_by_turn.append(tuple(sources))

    state = await store.sessions.get(session_id)
    assert state is not None
    versions = stamp(configuration, process)
    snapshot = await store.snapshot(session_id, versions=versions, taken_at=clock_at)
    assert snapshot is not None
    export = build_export(snapshot)
    result = SessionResult(
        state=state,
        turns=await store.turns.recent(session_id, 1000),
        spoken_by_turn=tuple(spoken_by_turn),
        sources_by_turn=tuple(sources_by_turn),
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
        judge=None,
        provider_failed=bool(failed_turns),
        latency_ms={},
        estimated_cost_eur=0.0,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evals")
    parser.add_argument(
        "--suite", choices=["scenarios", "retrieval", "comparison"], default="scenarios"
    )
    parser.add_argument("--mode", choices=["fake", "live"], default="fake")
    parser.add_argument("--only", nargs="*", default=[])
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--models", nargs="*", default=[])
    parser.add_argument("--judge", default="off")
    parser.add_argument("--retriever", choices=["hybrid", "lexical"], default="hybrid")
    parser.add_argument("--out", default=str(ROOT / "evals" / "results" / "retrieval"))
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args(argv)

    if args.list:
        for scenario in load_scenarios():
            print(f"{scenario.id}  {scenario.title}")
        return 0
    if args.suite == "retrieval":
        return retrieval_main(args.retriever, args.only, Path(args.out))
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


def retrieval_main(mode: str, only: Sequence[str], out: Path) -> int:
    """The 24 questions through the real retriever: ``hybrid`` needs the knowledge extra and
    downloads the model once; ``lexical`` is BM25 only and runs anywhere."""
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
    path = write_report(report, out)
    for run in report.runs:
        mark = {True: "hit ", False: "MISS", None: "    "}[run.hit] + (
            " LEAK" if run.leaked else ""
        )
        print(f"{mark} {run.case_id} {run.kind:<11} {run.milliseconds:>4} ms  {list(run.returned)}")
    print(
        f"recall@3 {report.recall_at_3:.0%} (n={report.answerable})  leaked {report.leaked}/"
        f"{len(report.runs)}  unsupported with sources {report.unsupported_with_sources}/4  "
        f"median {report.median_ms} ms  {report.embedding_model}  -> {path}"
    )
    return 0 if report.leaked == 0 else 1
