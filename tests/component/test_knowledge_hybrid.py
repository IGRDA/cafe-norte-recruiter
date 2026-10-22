"""Filter before rank, fusion of both rankers, the structured filter, lexical-only mode."""

from collections.abc import Sequence
from math import isclose, sqrt

import pytest

from cafe_norte.domain.contracts import ConfigId
from cafe_norte.knowledge.contracts import Index, RetrievalQuery, Vector
from cafe_norte.knowledge.fake import FakeEmbedder
from cafe_norte.knowledge.hybrid import HybridRetriever
from cafe_norte.knowledge.index import index_from_documents
from cafe_norte.knowledge.loader import load_documents
from tests.support import ROOT

CHAMBERI, ARGANZUELA = ConfigId("chamberi_barista_v1"), ConfigId("arganzuela_barista_v1")


@pytest.fixture(scope="module")
def index() -> Index:
    import asyncio

    return asyncio.run(
        index_from_documents(load_documents(ROOT / "kb"), FakeEmbedder(), kb_version="1")
    )


def query(*texts: str, config: ConfigId = CHAMBERI, **extra: object) -> RetrievalQuery:
    return RetrievalQuery(**{"queries": texts, "config_id": config, "kb_version": "1", **extra})


async def test_a_store_question_never_returns_the_other_stores_chunk(index: Index) -> None:
    retriever = HybridRetriever(index, FakeEmbedder())
    for config, other in ((CHAMBERI, "arganzuela"), (ARGANZUELA, "chamberi")):
        found = await retriever.retrieve(
            query(f"salario en {other} 800 euros 1.380 euros", config=config)
        )
        assert found and all(other not in r.chunk.doc_id for r in found)


async def test_both_rankers_contribute_and_results_come_best_first(index: Index) -> None:
    retriever = HybridRetriever(index, FakeEmbedder())
    found = await retriever.retrieve(query("cuántas horas a la semana"))
    assert found[0].chunk.chunk_id == "offer_chamberi#horas"
    assert found[0].bm25_rank == 1 and found[0].dense_rank is not None
    assert found[0].bm25_score > 0 and found[0].dense_score is not None
    assert [r.fused_score for r in found] == sorted((r.fused_score for r in found), reverse=True)
    assert len(found) <= 3


async def test_the_document_filter_narrows_the_documents(index: Index) -> None:
    retriever = HybridRetriever(index, FakeEmbedder())
    found = await retriever.retrieve(query("horas", doc_ids=frozenset({"uniform", "faq"})))
    assert found and {r.chunk.doc_id for r in found} <= {"uniform", "faq"}
    assert await retriever.retrieve(query("horas", doc_ids=frozenset({"nope"}))) == ()


async def test_lexical_only_mode_has_no_dense_rank_and_rejects_a_bad_pairing(index: Index) -> None:
    lexical = Index(manifest=index.manifest, chunks=index.chunks, vectors=None)
    found = await HybridRetriever(lexical, None).retrieve(query("uniforme delantal"))
    assert found[0].chunk.doc_id == "uniform" and found[0].dense_rank is None
    assert found[0].dense_score is None and found[0].bm25_score > 0
    with pytest.raises(ValueError):
        HybridRetriever(lexical, FakeEmbedder())


async def test_a_chunk_with_no_query_word_needs_a_cosine_above_the_floor(index: Index) -> None:
    # "xyzzy" shares no token with any chunk; fake vectors then decide, and the floor applies.
    permissive = HybridRetriever(index, FakeEmbedder(), dense_floor=-1.0)
    strict = HybridRetriever(index, FakeEmbedder(), dense_floor=1.01)
    assert await permissive.retrieve(query("xyzzy"))
    assert await strict.retrieve(query("xyzzy")) == ()
    # A lexical hit survives any floor.
    assert (await strict.retrieve(query("uniforme delantal")))[0].chunk.doc_id == "uniform"


async def test_nothing_matches_means_nothing_returned(index: Index) -> None:
    retriever = HybridRetriever(index, None)
    assert await retriever.retrieve(query("xyzzy")) == ()
    assert await retriever.retrieve(query("horas", kb_version="2")) == ()


async def test_a_second_phrasing_adds_its_evidence_and_the_best_rank_is_kept(index: Index) -> None:
    # The floor above 1 removes every chunk the first phrasing reaches by cosine alone; the
    # second phrasing brings lexical evidence, which survives any floor.
    retriever = HybridRetriever(index, FakeEmbedder(), dense_floor=1.01)
    one = await retriever.retrieve(query("zzqx"))
    two = await retriever.retrieve(query("zzqx", "uniforme delantal gorra"))
    assert one == () and two and two[0].chunk.doc_id == "uniform"
    assert two[0].bm25_rank == 1 and two[0].bm25_score > 0
    with pytest.raises(ValueError):
        query("a", "b", "c", "d")


def cosine(a: Vector, b: Vector) -> float:
    norm = sqrt(sum(x * x for x in a)) * sqrt(sum(y * y for y in b))
    return sum(x * y for x, y in zip(a, b, strict=True)) / norm if norm else 0.0


async def test_the_dense_score_is_the_cosine_of_query_and_chunk(index: Index) -> None:
    assert index.vectors is not None
    retriever = HybridRetriever(index, FakeEmbedder(), dense_floor=-1.0)
    (q,) = await FakeEmbedder().embed(["cuántas horas a la semana"])
    found = await retriever.retrieve(query("cuántas horas a la semana"))
    position = {c.chunk_id: i for i, c in enumerate(index.chunks)}
    assert found
    for r in found:
        assert r.dense_score is not None
        assert isclose(r.dense_score, cosine(q, index.vectors[position[r.chunk.chunk_id]]))


class ZeroEmbedder(FakeEmbedder):
    async def embed(self, texts: Sequence[str]) -> tuple[Vector, ...]:
        return tuple((0.0,) * self.DIMENSIONS for _ in texts)


async def test_a_zero_vector_has_no_cosine_and_no_dense_rank(index: Index) -> None:
    found = await HybridRetriever(index, ZeroEmbedder()).retrieve(query("uniforme delantal"))
    assert found and all(r.dense_score == 0.0 and r.dense_rank is None for r in found)


@pytest.mark.parametrize(
    ("question", "section"),
    [  # the model's own queries from the gpt-4.1 baseline (D53)
        (
            "¿Cuántos días de vacaciones tiene el puesto de barista en Café Norte Chamberí?",
            "offer_chamberi#vacaciones",
        ),
        ("horas semanales del puesto de barista en Café Norte Chamberí", "offer_chamberi#horas"),
        (
            "¿Qué tipo de contrato tiene el puesto de barista en Café Norte Chamberí?",
            "offer_chamberi#contrato",
        ),
    ],
)
async def test_words_every_document_shares_do_not_drown_the_question(
    index: Index, question: str, section: str
) -> None:
    found = await HybridRetriever(index, None).retrieve(query(question))
    assert section in [r.chunk.chunk_id for r in found]
