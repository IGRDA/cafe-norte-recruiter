"""Tokenizer, BM25 against a hand-computed case, the fake embedder, and the artifact round trip."""

import math
from pathlib import Path

import pytest

from cafe_norte.knowledge.bm25 import BM25, tokenize
from cafe_norte.knowledge.fake import FakeEmbedder
from cafe_norte.knowledge.index import build_index, index_from_documents, load_index, load_manifest
from cafe_norte.knowledge.loader import load_documents
from tests.support import ROOT

KB = ROOT / "kb"


def test_tokenizer_lowercases_strips_accents_and_drops_stopwords() -> None:
    assert tokenize("¿Cuántas HORAS a la semana son en Chamberí?") == (
        "cuantas",
        "horas",
        "semana",
        "son",
        "chamberi",
    )
    assert tokenize("07:00 a 21:00") == ("07", "00", "21", "00")


def test_bm25_matches_the_formula_on_a_tiny_corpus() -> None:
    docs = (("cafe", "horas"), ("cafe", "cafe", "turno"), ("sueldo",))
    scores = BM25(docs).scores(("cafe",))
    # idf = ln(1 + (3 - 2 + 0.5) / (2 + 0.5)); average length (2 + 3 + 1) / 3
    idf = math.log(1 + 1.5 / 2.5)
    avg = 2.0

    def expected(tf: int, length: int) -> float:
        return idf * tf * 2.5 / (tf + 1.5 * (0.25 + 0.75 * length / avg))

    assert scores == pytest.approx((expected(1, 2), expected(2, 3), 0.0))
    assert BM25(()).scores(("x",)) == ()


async def test_fake_embedder_is_deterministic_normalised_and_rewards_shared_words() -> None:
    embedder = FakeEmbedder()
    a, b, c = await embedder.embed(["horas a la semana", "cuántas horas semanales", "uniforme"])
    assert a == (await embedder.embed(["horas a la semana"]))[0]
    assert math.isclose(sum(x * x for x in a), 1.0)
    assert sum(x * y for x, y in zip(a, b, strict=True)) > sum(
        x * y for x, y in zip(a, c, strict=True)
    )


async def test_in_memory_index_covers_every_chunk_with_or_without_vectors() -> None:
    documents = load_documents(KB)
    lexical = await index_from_documents(documents, None, kb_version="1")
    assert lexical.vectors is None and lexical.manifest.embedding_model == "none"
    dense = await index_from_documents(documents, FakeEmbedder(), kb_version="1")
    assert dense.vectors is not None and len(dense.vectors) == len(dense.chunks)
    assert dense.manifest.chunk_count == len(dense.chunks) == lexical.manifest.chunk_count
    assert set(dense.manifest.document_hashes) == {d.doc_id for d in documents}


async def test_artifact_round_trips_and_refuses_a_mismatch(tmp_path: Path) -> None:
    documents = load_documents(KB)
    manifest = await build_index(documents, FakeEmbedder(), tmp_path, kb_version="1")
    assert sorted(p.name for p in (tmp_path / "1").iterdir()) == [
        "chunks.json",
        "manifest.json",
        "vectors.json",
    ]
    assert load_manifest(tmp_path, kb_version="1") == manifest
    loaded = load_index(tmp_path, kb_version="1")
    assert loaded == await index_from_documents(documents, FakeEmbedder(), kb_version="1")
    (tmp_path / "1" / "vectors.json").write_text("[]")
    with pytest.raises(ValueError, match="disagree"):
        load_index(tmp_path, kb_version="1")
