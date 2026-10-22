"""The retrieval suite scores a retriever against the fixture; BM25 alone already finds the
Spanish answerable questions and never leaks."""

from pathlib import Path

from evals.retrieval import load_cases, recorded_queries, replay, run_retrieval, write_report
from evals.runner import load_scenarios, run_fake

from cafe_norte.domain.configuration import load_configurations
from cafe_norte.knowledge.hybrid import HybridRetriever
from cafe_norte.knowledge.index import lexical_index
from cafe_norte.knowledge.loader import load_documents
from tests.support import CONFIG_DIR, ROOT


async def test_lexical_retrieval_hits_every_spanish_answerable_question_and_never_leaks(
    tmp_path: Path,
) -> None:
    configurations = load_configurations(CONFIG_DIR)
    retriever = HybridRetriever(lexical_index(load_documents(ROOT / "kb"), kb_version="2"), None)
    report = await run_retrieval(load_cases(), retriever, configurations)
    assert len(report.runs) == 41 and report.answerable == 32 and report.leaked == 0
    spanish = [r for r in report.runs if r.kind == "answerable" and r.case_id in SPANISH]
    assert all(r.hit for r in spanish), [r.case_id for r in spanish if not r.hit]
    assert report.embedding_model == "none"
    path = write_report(report, tmp_path)
    assert path.name == "none-kb2.json" and '"recall_at_3"' in path.read_text()


SPANISH = {
    *("R01", "R02", "R03", "R04", "R09", "R10", "R11", "R12"),
    *("R25", "R29", "R33", "R34", "R36", "R37", "R38", "R40"),
}


async def test_the_models_recorded_queries_replay_through_todays_retriever(
    tmp_path: Path,
) -> None:
    (scenario,) = load_scenarios(only=["S05"])  # its fake model searches for the hours
    record = await run_fake(scenario)
    assert record.export is not None
    (tmp_path / "R01.json").write_text(record.export.model_dump_json())

    recorded = recorded_queries(tmp_path)
    assert recorded == {
        "R01": (("¿Cuántas horas a la semana tiene la jornada?", "horas semanales del puesto"),)
    }
    configurations = load_configurations(CONFIG_DIR)
    retriever = HybridRetriever(lexical_index(load_documents(ROOT / "kb"), kb_version="2"), None)
    hits, searched, misses = await replay(load_cases(), recorded, retriever, configurations)
    assert (hits, searched, misses) == (1, 1, [])
