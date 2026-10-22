"""Cases as a Langfuse dataset and runs as experiment runs, through a port: the fake records
what would be sent, a stub stands in for the SDK client. No network, no keys."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from evals.contracts import CheckResult, Extraction, Report, RunRecord
from evals.langfuse_sync import FakeSink, SdkSink, dataset_items, experiment_runs, sync
from evals.langfuse_sync import main as langfuse_main
from evals.report import render_json
from evals.runner import comparison_plan, main

from cafe_norte.observability.contracts import VersionStamp

VERSIONS = VersionStamp(
    config_id="chamberi_barista_v1",
    config_version="1",
    kb_version="2",
    prompt_version="ana_v15",
    schema_version="1",
    model_id="gpt-4o",
    commit_sha="abc1234",
)
PLAN = comparison_plan(["openai/gpt-4o-mini", "openai/gpt-4o"], repeat=2)


def run(case: str, model: str, rep: int, *, ok: bool = True) -> RunRecord:
    return RunRecord(
        case_id=case,
        scenario_id="S04",
        mode="live",
        model=model,
        repetition=rep,
        session_id=f"sess-{case}-{model}-{rep}",
        versions=VERSIONS,
        export=None,
        checks=(CheckResult(name="brief_confirmed", ok=ok, detail="d"),),
        judge=None,
        provider_failed=False,
        estimated_cost_eur=0.004,
        extraction=Extraction(correct=6, supplied=7),
        lines=9,
        cost_is_partial=False,
    )


REPORT = Report(
    suite="comparison",
    runs=(
        run("C1", "openai/gpt-4o", 1),
        run("C2", "openai/gpt-4o", 1, ok=False),
        run("C1", "openai/gpt-4o", 2),
    ),
    denominators={},
)


def test_each_case_is_one_dataset_item_with_its_checks_as_expected_output() -> None:
    items = dataset_items(PLAN, "comparison")
    assert [i.item_id for i in items] == [f"cafe-norte-comparison-C{n}" for n in range(1, 7)]
    first = items[0]
    assert first.input["scenario_id"] == "S04"
    assert first.metadata["emphasis"] == "correction"
    assert {"name": "brief_confirmed", "args": {}} in first.expected_output["live_checks"]


def test_runs_group_by_model_and_repetition_with_scores_and_session() -> None:
    runs = experiment_runs(REPORT)
    assert [r.run_name for r in runs] == [
        "ana_v15 · openai/gpt-4o · r1",
        "ana_v15 · openai/gpt-4o · r2",
    ]
    row = runs[0].rows[1]
    assert row.item_id == "cafe-norte-comparison-C2"
    assert row.session_id == "sess-C2-openai/gpt-4o-1"
    assert row.scores["passed"] is False
    assert row.scores["check.brief_confirmed"] is False
    assert row.scores["extraction"] == 6 / 7
    assert row.scores["cost_eur"] == 0.004


def test_sync_upserts_the_dataset_then_records_every_run() -> None:
    sink = FakeSink()
    sync(REPORT, PLAN, sink)
    assert sink.datasets == ["cafe-norte-comparison"]
    assert len(sink.items["cafe-norte-comparison"]) == 6
    assert [name for _, name, _ in sink.runs] == [r.run_name for r in experiment_runs(REPORT)]


class StubClient:
    """The few SDK calls SdkSink makes, recorded."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.task_outputs: list[Any] = []
        self.evaluations: list[Any] = []

    def create_dataset(self, **kwargs: Any) -> None:
        self.calls.append(("create_dataset", kwargs))

    def create_dataset_item(self, **kwargs: Any) -> None:
        self.calls.append(("create_dataset_item", kwargs))

    def get_dataset(self, name: str) -> Any:
        class Item:
            def __init__(self, id_: str) -> None:
                self.id = id_

        class Dataset:
            items = [Item("cafe-norte-comparison-C1"), Item("cafe-norte-comparison-C2")]

        return Dataset()

    def run_experiment(
        self, *, name: str, run_name: str, data: list[Any], task: Callable[..., Any],
        evaluators: list[Callable[..., Any]], **kwargs: Any,
    ) -> None:  # fmt: skip
        self.calls.append(("run_experiment", {"name": name, "run_name": run_name}))
        for item in data:
            output = task(item=item)
            self.task_outputs.append(output)
            for evaluator in evaluators:
                self.evaluations += evaluator(
                    input=None, output=output, expected_output=None, item=item
                )

    @contextmanager
    def start_as_current_observation(self, **kwargs: Any) -> Iterator[None]:
        self.calls.append(("observation", kwargs))
        yield

    def flush(self) -> None:
        self.calls.append(("flush", {}))


def test_the_sdk_sink_replays_recorded_runs_through_the_experiment_runner() -> None:
    client = StubClient()
    sync(REPORT, PLAN, SdkSink(client))
    names = [name for name, _ in client.calls]
    assert names[0] == "create_dataset" and names.count("create_dataset_item") == 6
    assert names.count("run_experiment") == 2 and names[-1] == "flush"
    assert client.task_outputs[0]["lines"] == 9
    passed = [e for e in client.evaluations if e.name == "passed"]
    assert [e.value for e in passed] == [True, False, True]


def test_nothing_is_sent_without_keys(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    written = tmp_path / "report.json"
    written.write_text(render_json(REPORT, generated_at=datetime(2026, 10, 21, tzinfo=UTC)))
    assert langfuse_main([str(written)]) == 2
    assert langfuse_main([]) == 2
    assert "not set" in capsys.readouterr().out


def test_a_live_run_with_langfuse_and_no_keys_says_it_skipped(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    args = ["--suite", "scenarios", "--mode", "live", "--only", "S01", "--model", "fake"]
    args += ["--simulator", "fake", "--max-turns", "1", "--out", str(tmp_path), "--langfuse"]
    main([*args, "--yes"])
    assert "Langfuse: skipped" in capsys.readouterr().out
