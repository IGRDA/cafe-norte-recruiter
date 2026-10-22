"""Retrieval runs as ragas samples, scored by ragas' ID-based context precision and recall:
offline, no model, next to our own recall@3 (D06)."""

import json
from pathlib import Path

import pytest
from evals.contracts import RagasSample, RetrievalCase, RetrievalRun
from evals.ragas_bridge import score_with_ragas, to_ragas_samples
from evals.retrieval import load_cases
from evals.runner import main

from cafe_norte.domain.contracts import ConfigId


def case(id_: str, kind: str = "answerable", sections: tuple[str, ...] = ()) -> RetrievalCase:
    return RetrievalCase(
        id=id_,
        question=f"¿{id_}?",
        config_id=ConfigId("chamberi_barista_v1"),
        language="es",
        kind=kind,
        expected_sections=sections,
    )


def run(id_: str, returned: tuple[str, ...], kind: str = "answerable") -> RetrievalRun:
    return RetrievalRun(
        case_id=id_,
        kind=kind,
        returned=returned,
        fused_scores=(0.03,) * len(returned),
        hit=None,
        leaked=False,
        milliseconds=5,
    )


def test_only_answerable_questions_become_samples() -> None:
    cases = [case("R01", sections=("offer#horas",)), case("R17", "unsupported")]
    runs = [run("R01", ("offer#horas", "faq#x")), run("R17", ("faq#y",), "unsupported")]
    assert to_ragas_samples(runs, cases) == [
        RagasSample(
            case_id="R01",
            user_input="¿R01?",
            retrieved_context_ids=("offer#horas", "faq#x"),
            reference_context_ids=("offer#horas",),
        )
    ]


async def test_ragas_scores_precision_and_recall_per_question() -> None:
    samples = [
        RagasSample(
            case_id="R01",
            user_input="q",
            retrieved_context_ids=("a#1", "b#2", "c#3"),
            reference_context_ids=("b#2",),
        ),
        RagasSample(
            case_id="R02", user_input="q", retrieved_context_ids=(), reference_context_ids=("x#1",)
        ),
    ]
    scores = await score_with_ragas(samples)
    assert scores.samples == 2
    assert [s.precision for s in scores.per_case] == [pytest.approx(1 / 3), None]
    assert [s.recall for s in scores.per_case] == [1.0, 0.0]
    assert scores.mean_recall == 0.5
    assert scores.mean_precision == pytest.approx(1 / 3)  # n=1: nothing retrieved is no precision
    assert scores.nothing_retrieved == 1


def test_the_fixture_gives_sixteen_samples() -> None:
    cases = load_cases()
    runs = [run(c.id, c.expected_sections, c.kind) for c in cases]
    assert len(to_ragas_samples(runs, cases)) == 16


def test_the_retrieval_suite_adds_ragas_when_asked(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        ["--suite", "retrieval", "--retriever", "lexical", "--ragas", "--out", str(tmp_path)]
    )
    assert code == 0
    (written,) = tmp_path.glob("*.json")
    ragas = json.loads(written.read_text())["ragas"]
    assert ragas["samples"] == 16
    assert "ragas" in capsys.readouterr().out
