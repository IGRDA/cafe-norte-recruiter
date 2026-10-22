"""The ragas testset's pure parts (D51): generated rows back to our chunk ids, a priced
estimate before any spend, and the knowledge-base questions as a Langfuse dataset."""

import math
from typing import Any

import pytest
from evals.langfuse_sync import RAG_DATASET, FakeSink, rag_items, sync_rag_dataset
from evals.retrieval import load_cases
from evals.testset import candidates, estimate, kb_chunks, main


def test_reference_contexts_map_back_to_chunk_ids_hop_markers_and_all() -> None:
    chunks = kb_chunks()
    salary = next(c for c in chunks if c.chunk_id == "offer_chamberi#salario")
    team = next(c for c in chunks if c.chunk_id == "store_chamberi#equipo")
    rows: list[dict[str, Any]] = [
        {
            "user_input": " How much is it? ",
            "reference": "1.380 euros",
            "reference_contexts": [salary.text.replace(" ", "  ")],
            "synthesizer_name": "single_hop_specific_query_synthesizer",
            "persona_name": "Expat",
        },
        {
            "user_input": "¿Quién entrevista y cuánto pagan?",
            "reference": "Marta; 1.380 euros",
            "reference_contexts": [f"<1-hop>\n\n{team.text}", f"<2-hop>\n\n{salary.text}", "x"],
            "synthesizer_name": "multi_hop_specific_query_synthesizer",
            "persona_name": math.nan,
        },
    ]
    first, second = candidates(rows, chunks)
    assert first.question == "How much is it?" and first.chunk_ids == ("offer_chamberi#salario",)
    assert second.chunk_ids == ("store_chamberi#equipo", "offer_chamberi#salario", "?")
    assert second.persona == ""


def test_the_estimate_prices_every_model_and_nothing_runs_without_yes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    spend = estimate(40, len(kb_chunks()))
    assert spend.eur > 0 and spend.unpriced == ()
    assert main(["--size", "2"]) == 0
    assert "Nothing was spent" in capsys.readouterr().out


def test_the_questions_become_one_dataset_item_each_with_their_reference() -> None:
    cases = load_cases()
    sink = FakeSink()
    sync_rag_dataset(cases, sink)
    items = sink.items[RAG_DATASET]
    assert sink.datasets == [RAG_DATASET] and len(items) == len(cases) == len(rag_items(cases))
    r25 = next(i for i in items if i.metadata["case_id"] == "R25")
    assert r25.item_id == "cafe-norte-rag-R25" and r25.metadata["origin"] == "ragas"
    assert r25.expected_output["reference"].startswith("Sí, hace falta")
