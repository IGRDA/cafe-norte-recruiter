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

from cafe_norte.conversation.contracts import AssistantText, TurnFailed, TurnInput
from cafe_norte.conversation.handlers import all_handlers
from cafe_norte.conversation.prompts import PROMPT_VERSION
from cafe_norte.conversation.registry import ToolRegistry
from cafe_norte.conversation.runtime import Limits, Runtime
from cafe_norte.domain.configuration import load_configurations
from cafe_norte.domain.contracts import InputId, SessionId, SessionState
from cafe_norte.knowledge.fake import FakeRetriever
from cafe_norte.model.contracts import ModelEvent, ModelFinished, ModelText, ToolCall
from cafe_norte.model.fake import FakeModel
from cafe_norte.observability.contracts import ProcessVersions, stamp
from cafe_norte.persistence.export import SCHEMA_VERSION, build_export
from cafe_norte.persistence.memory import MemoryStore
from evals.contracts import RunRecord, Scenario, SessionResult, Step
from evals.scorers import run_check

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS_DIR = ROOT / "evals" / "cases" / "scenarios"
CONFIG_DIR = ROOT / "config"


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


async def run_fake(scenario: Scenario) -> RunRecord:
    """Replay the scenario: open the session, one turn per candidate line, then the checks."""
    store = MemoryStore()
    configurations = load_configurations(CONFIG_DIR)
    configuration = configurations[scenario.config_id]
    clock_at = datetime.combine(datetime.fromisoformat(scenario.today), time(10, 0), tzinfo=UTC)
    scripts = [round_ for steps in scenario.fake_script for round_ in script_events(steps)]
    model = FakeModel(scripts)
    runtime = Runtime(
        model=model,
        tools=ToolRegistry(
            all_handlers(store=store, configurations=configurations, retriever=FakeRetriever())
        ),
        store=store,
        configurations=configurations,
        signals=None,
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
        async for event in runtime.run_turn(turn):
            if isinstance(event, AssistantText):
                spoken.append(event.text)
            elif isinstance(event, TurnFailed):
                failed_turns.append(f"turn {index + 1}: {event.code}")
        spoken_by_turn.append(tuple(spoken))

    state = await store.sessions.get(session_id)
    assert state is not None
    result = SessionResult(
        state=state,
        turns=await store.turns.recent(session_id, 1000),
        spoken_by_turn=tuple(spoken_by_turn),
    )
    checks = tuple(run_check(result, check) for check in scenario.checks)
    versions = stamp(configuration, process)
    snapshot = await store.snapshot(session_id, versions=versions, taken_at=clock_at)
    assert snapshot is not None
    return RunRecord(
        case_id=scenario.id,
        mode="fake",
        versions=versions,
        export=build_export(snapshot),
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
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args(argv)

    if args.list:
        for scenario in load_scenarios():
            print(f"{scenario.id}  {scenario.title}")
        return 0
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
