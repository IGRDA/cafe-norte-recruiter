"""Cases as a Langfuse dataset and runs as experiment runs, so traces, scores and prompt
versions line up in one place.

The mapping is pure (``dataset_items``, ``experiment_runs``); ``ExperimentSink`` is the port.
``SdkSink`` replays runs that already happened through the SDK's experiment runner (the
supported way to write experiments since the dataset-run-items endpoint was deprecated): the
task returns the recorded outcome, the evaluators return our checks as scores, and a span
inside the task carries the run's ``session_id`` so the experiment item sits next to the
server's own turn traces. Nothing is re-run and nothing is judged here."""

import os
import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from evals.contracts import ProbeRecord, Report, RetrievalCase, RunRecord
from evals.scorers import abstained, facts_missing

PREFIX = "cafe-norte"
RAG_DATASET = f"{PREFIX}-rag"  # the knowledge-base questions, probed one session each


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PlannedCase(Protocol):
    """What a dataset item needs from a planned run (``evals.live_runs.Planned``)."""

    @property
    def case_id(self) -> str: ...

    @property
    def emphasis(self) -> str: ...

    @property
    def scenario(self) -> Any: ...


class DatasetItem(Frozen):
    item_id: str
    input: dict[str, Any]  # JSON payload
    expected_output: dict[str, Any]  # JSON payload
    metadata: dict[str, str]


class ExperimentRow(Frozen):
    item_id: str
    session_id: str
    output: dict[str, Any]  # JSON payload: the recorded outcome
    scores: dict[str, bool | float]


class ExperimentRun(Frozen):
    run_name: str
    metadata: dict[str, str]
    rows: tuple[ExperimentRow, ...]


class ExperimentSink(Protocol):
    def upsert_dataset(self, name: str, description: str) -> None: ...

    def upsert_items(self, dataset: str, items: Sequence[DatasetItem]) -> None: ...

    def record_run(self, dataset: str, run: ExperimentRun) -> None: ...


def dataset_name(suite: str) -> str:
    return f"{PREFIX}-{suite}"


def dataset_items(plan: Sequence[PlannedCase], suite: str) -> list[DatasetItem]:
    """One item per case, in plan order; the id is stable so a re-sync updates in place."""
    seen: dict[str, DatasetItem] = {}
    for planned in plan:
        if planned.case_id in seen:
            continue
        scenario = planned.scenario
        seen[planned.case_id] = DatasetItem(
            item_id=f"{dataset_name(suite)}-{planned.case_id}",
            input={
                "scenario_id": scenario.id,
                "title": scenario.title,
                "config_id": scenario.config_id,
                "language": scenario.language,
                "persona": scenario.persona.model_dump(mode="json"),
            },
            expected_output={
                "live_checks": [c.model_dump(mode="json") for c in scenario.live_checks],
                "rubric": list(scenario.rubric),
            },
            metadata={"case_id": planned.case_id, "emphasis": planned.emphasis},
        )
    return list(seen.values())


def rag_items(cases: Sequence[RetrievalCase]) -> list[DatasetItem]:
    """The knowledge-base questions: the question and its store in, the reference answer,
    sections and facts out. Ids are the case ids, so a re-sync updates in place."""
    return [
        DatasetItem(
            item_id=f"{RAG_DATASET}-{case.id}",
            input={
                "question": case.question,
                "config_id": case.config_id,
                "language": case.language,
            },
            expected_output={
                "kind": case.kind,
                "reference": case.reference,
                "expected_sections": list(case.expected_sections),
                "expected_facts": list(case.expected_facts),
            },
            metadata={"case_id": case.id, "origin": case.origin},
        )
        for case in cases
    ]


def sync_rag_dataset(cases: Sequence[RetrievalCase], sink: ExperimentSink) -> None:
    sink.upsert_dataset(RAG_DATASET, "Café Norte knowledge-base questions (evals/cases/retrieval)")
    sink.upsert_items(RAG_DATASET, rag_items(cases))


def probe_run(probes: Sequence[ProbeRecord], model: str) -> ExperimentRun:
    """The probes of one scorecard as one experiment run on ``cafe-norte-rag``: the answer as
    output, the deterministic reads and ragas' scores as scores."""
    stamp = next((p.run.versions for p in probes if p.run.versions is not None), None)
    prompt = stamp.prompt_version if stamp else "unknown"
    rows: list[ExperimentRow] = []
    for probe in probes:
        scores: dict[str, bool | float] = {k: v for k, v in probe.scores.items() if v is not None}
        if probe.run.export is not None and probe.kind == "answerable":
            missing = facts_missing(probe.answer, probe.expected_facts)
            scores["fact_presence"] = 1 - len(missing) / max(len(probe.expected_facts), 1)
        if probe.run.export is not None and probe.kind == "unsupported":
            scores["abstention"] = abstained(probe.answer, probe.tools)
        rows.append(
            ExperimentRow(
                item_id=f"{RAG_DATASET}-{probe.case_id}",
                session_id=probe.run.session_id,
                output={
                    "answer": probe.answer,
                    "sources": list(probe.sources),
                    "tools": list(probe.tools),
                    "failure": probe.run.failure,
                },
                scores=scores,
            )
        )
    return ExperimentRun(
        run_name=f"{prompt} · {model} · probes",
        metadata={
            "model": model,
            "prompt_version": prompt,
            "kb_version": stamp.kb_version if stamp else "",
        },
        rows=tuple(rows),
    )


def experiment_runs(report: Report) -> list[ExperimentRun]:
    """One experiment run per (model, repetition), named ``<prompt> · <model> · r<n>``."""
    groups: dict[tuple[str, int], list[RunRecord]] = {}
    for record in report.runs:
        groups.setdefault((record.model, record.repetition), []).append(record)
    runs: list[ExperimentRun] = []
    for (model, repetition), records in groups.items():
        stamp = next((r.versions for r in records if r.versions is not None), None)
        prompt = stamp.prompt_version if stamp else "unknown"
        runs.append(
            ExperimentRun(
                run_name=f"{prompt} · {model} · r{repetition}",
                metadata={
                    "model": model,
                    "prompt_version": prompt,
                    "kb_version": stamp.kb_version if stamp else "",
                    "commit_sha": stamp.commit_sha if stamp else "",
                },
                rows=tuple(_row(report.suite, r) for r in records),
            )
        )
    return runs


def sync(report: Report, plan: Sequence[PlannedCase], sink: ExperimentSink) -> None:
    name = dataset_name(report.suite)
    sink.upsert_dataset(name, f"Café Norte {report.suite} cases (evals/cases)")
    sink.upsert_items(name, dataset_items(plan, report.suite))
    for run in experiment_runs(report):
        sink.record_run(name, run)


def keys_present(env: dict[str, str] | None = None) -> bool:
    env = env if env is not None else dict(os.environ)
    return bool(env.get("LANGFUSE_PUBLIC_KEY") and env.get("LANGFUSE_SECRET_KEY"))


class FakeSink:
    """Records what would be sent."""

    def __init__(self) -> None:
        self.datasets: list[str] = []
        self.items: dict[str, list[DatasetItem]] = {}
        self.runs: list[tuple[str, str, ExperimentRun]] = []

    def upsert_dataset(self, name: str, description: str) -> None:
        self.datasets.append(name)

    def upsert_items(self, dataset: str, items: Sequence[DatasetItem]) -> None:
        self.items[dataset] = list(items)

    def record_run(self, dataset: str, run: ExperimentRun) -> None:
        self.runs.append((dataset, run.run_name, run))


class SdkSink:
    """The Langfuse Python SDK (an evaluation dependency, never imported by ``src/``)."""

    def __init__(self, client: Any) -> None:
        self._client = client

    @classmethod
    def from_env(cls) -> "SdkSink":
        from langfuse import Langfuse

        host = os.environ.get("LANGFUSE_BASE_URL", "https://cloud.langfuse.com")
        return cls(Langfuse(host=host))

    def upsert_dataset(self, name: str, description: str) -> None:
        self._client.create_dataset(name=name, description=description)  # upsert by name

    def upsert_items(self, dataset: str, items: Sequence[DatasetItem]) -> None:
        for item in items:
            self._client.create_dataset_item(
                dataset_name=dataset,
                id=item.item_id,  # upsert by id
                input=item.input,
                expected_output=item.expected_output,
                metadata=item.metadata,
            )

    def record_run(self, dataset: str, run: ExperimentRun) -> None:
        rows = {row.item_id: row for row in run.rows}
        items = [i for i in self._client.get_dataset(dataset).items if i.id in rows]

        def task(*, item: Any, **_: Any) -> dict[str, Any]:
            row = rows[item.id]
            with self._session(row.session_id):
                with self._client.start_as_current_observation(
                    name="recorded-live-run", output=row.output
                ):
                    pass
            return {**row.output, "scores": row.scores}

        def evaluate(*, output: dict[str, Any], **_: Any) -> list[Any]:
            from langfuse import Evaluation

            return [Evaluation(name=k, value=v) for k, v in output["scores"].items()]

        self._client.run_experiment(
            name=dataset,
            run_name=run.run_name,
            data=items,
            task=task,
            evaluators=[evaluate],
            metadata=run.metadata,
            max_concurrency=1,
        )
        self._client.flush()

    @staticmethod
    @contextmanager
    def _session(session_id: str) -> Iterator[None]:
        from langfuse import propagate_attributes

        with propagate_attributes(session_id=session_id or None, tags=["evaluation"]):
            yield


def _row(suite: str, record: RunRecord) -> ExperimentRow:
    scores: dict[str, bool | float] = {"passed": record.passed}
    scores |= {f"check.{c.name}": c.ok for c in record.checks}
    if record.extraction is not None and record.extraction.supplied:
        scores["extraction"] = record.extraction.correct / record.extraction.supplied
    if record.estimated_cost_eur is not None:
        scores["cost_eur"] = record.estimated_cost_eur
    scores |= {f"judge.{k}": v for k, v in record.scores.items() if v is not None}
    return ExperimentRow(
        item_id=f"{dataset_name(suite)}-{record.case_id}",
        session_id=record.session_id,
        output={
            "lines": record.lines,
            "failure": record.failure,
            "failed_checks": [f"{c.name}: {c.detail}" for c in record.checks if not c.ok],
            "extraction_misses": list(record.extraction.misses) if record.extraction else [],
            "first_text_ms": list(record.first_text_ms),
            "model": record.model,
            "repetition": record.repetition,
        },
        scores=scores,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m evals.langfuse_sync <report.json>``: sync a written report afterwards;
    ``--rag``: the knowledge-base questions as their own dataset."""
    from evals.report import ReportFile
    from evals.runner import comparison_plan, load_scenarios

    args = list(argv if argv is not None else sys.argv[1:])
    if len(args) != 1:
        print("usage: python -m evals.langfuse_sync <report.json> | --rag")
        return 2
    if not keys_present():
        print("LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are not set: nothing sent.")
        return 2
    if args[0] == "--rag":
        from evals.retrieval import load_cases

        cases = load_cases()
        sync_rag_dataset(cases, SdkSink.from_env())
        print(f"synced {len(cases)} questions to dataset {RAG_DATASET}")
        return 0
    written = ReportFile.model_validate_json(Path(args[0]).read_text(encoding="utf-8"))
    report = Report(suite=written.suite, runs=written.runs, denominators=written.denominators)
    if report.suite == "comparison":
        plan: Sequence[PlannedCase] = comparison_plan(
            sorted({r.model for r in report.runs}), repeat=1
        )
    else:
        plan = _scenario_plan(load_scenarios(only=sorted({r.case_id for r in report.runs})))
    sync(report, plan, SdkSink.from_env())
    print(f"synced {len(report.runs)} runs to dataset {dataset_name(report.suite)}")
    return 0


def _scenario_plan(scenarios: Sequence[Any]) -> list[PlannedCase]:
    from evals.live_runs import Planned

    return [Planned(case_id=s.id, scenario=s, model="", repetition=1) for s in scenarios]


if __name__ == "__main__":
    raise SystemExit(main())
