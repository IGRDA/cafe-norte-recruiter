"""The retrieval suite: the fixture's questions through a retriever, scored without a model.

Recall@3 counts a hit when any expected section is among the returned chunks; leakage is a
returned chunk outside the configuration's documents. Unsupported questions are reported with
what came back: stage 1 has no relevance floor, so abstention is the prompt's job and is
measured by the scenario judge, not here."""

import json
import statistics
import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

import yaml

from cafe_norte.domain.contracts import ConfigId, StoreConfiguration
from cafe_norte.knowledge.contracts import RetrievalQuery, Retriever
from evals.contracts import RetrievalCase, RetrievalReport, RetrievalRun

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "evals" / "cases" / "retrieval" / "questions.yaml"


def load_cases(path: Path = FIXTURE) -> list[RetrievalCase]:
    return [RetrievalCase.model_validate(c) for c in yaml.safe_load(path.read_text())]


async def run_retrieval(
    cases: Sequence[RetrievalCase],
    retriever: Retriever,
    configurations: Mapping[ConfigId, StoreConfiguration],
) -> RetrievalReport:
    runs: list[RetrievalRun] = []
    for case in cases:
        configuration = configurations[case.config_id]
        started = time.monotonic()
        found = await retriever.retrieve(
            RetrievalQuery(
                text=case.question, config_id=case.config_id, kb_version=configuration.kb_version
            )
        )
        elapsed = int((time.monotonic() - started) * 1000)
        returned = tuple(r.chunk.chunk_id for r in found)
        runs.append(
            RetrievalRun(
                case_id=case.id,
                kind=case.kind,
                returned=returned,
                fused_scores=tuple(round(r.fused_score, 5) for r in found),
                hit=any(s in returned for s in case.expected_sections)
                if case.kind == "answerable"
                else None,
                leaked=any(c.split("#")[0] not in configuration.kb_doc_ids for c in returned),
                milliseconds=elapsed,
            )
        )
    answerable = [r for r in runs if r.kind == "answerable"]
    manifest = retriever.manifest
    return RetrievalReport(
        kb_version=manifest.kb_version,
        embedding_model=manifest.embedding_model,
        embedding_revision=manifest.embedding_revision,
        runs=tuple(runs),
        recall_at_3=(sum(1 for r in answerable if r.hit) / len(answerable)) if answerable else 0.0,
        answerable=len(answerable),
        leaked=sum(1 for r in runs if r.leaked),
        unsupported_with_sources=sum(1 for r in runs if r.kind == "unsupported" and r.returned),
        median_ms=int(statistics.median(r.milliseconds for r in runs)) if runs else 0,
    )


def write_report(report: RetrievalReport, directory: Path) -> Path:
    """``<model>-kb<version>.json``: one committed file per retriever configuration, so a rerun
    shows its diff."""
    directory.mkdir(parents=True, exist_ok=True)
    model = report.embedding_model.split("/")[-1]
    path = directory / f"{model}-kb{report.kb_version}.json"
    payload = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        **report.model_dump(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return path
