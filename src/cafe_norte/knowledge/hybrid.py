"""BM25 + dense cosine, reciprocal rank fusion, filtered by store before ranking."""

from math import sqrt

from cafe_norte.knowledge.bm25 import BM25, tokenize
from cafe_norte.knowledge.contracts import (
    Chunk,
    Embedder,
    Index,
    IndexManifest,
    RetrievalQuery,
    RetrievedChunk,
    Vector,
)

RRF_K = 60


def lexical_text(chunk: Chunk) -> str:
    """What BM25 sees: title, section and text. The bilingual title makes English hit."""
    return f"{chunk.title} {chunk.section} {chunk.text}"


class HybridRetriever:
    """Allowed chunks are those of the query's configuration, KB version and, when given,
    document ids; both rankers rank among allowed chunks only, so a chunk of another store
    can never outrank anything. Without an embedder the retriever is BM25 only."""

    def __init__(self, index: Index, embedder: Embedder | None, *, rrf_k: int = RRF_K) -> None:
        if embedder is not None and index.vectors is None:
            raise ValueError("an embedder needs an index with vectors")
        self._index = index
        self._embedder = embedder
        self._k = rrf_k
        self._bm25 = BM25(tuple(tokenize(lexical_text(c)) for c in index.chunks))

    @property
    def manifest(self) -> IndexManifest:
        return self._index.manifest

    async def retrieve(self, query: RetrievalQuery) -> tuple[RetrievedChunk, ...]:
        if query.kb_version != self.manifest.kb_version:
            return ()
        allowed = [
            i
            for i, c in enumerate(self._index.chunks)
            if query.config_id in c.config_ids
            and (query.doc_ids is None or c.doc_id in query.doc_ids)
        ]
        if not allowed:
            return ()
        rankings: list[dict[int, int]] = [_ranks(allowed, self._bm25.scores(tokenize(query.text)))]
        if self._embedder is not None and self._index.vectors is not None:
            (vector,) = await self._embedder.embed([query.text])
            vectors = self._index.vectors
            rankings.append(_ranks(allowed, [_cosine(vector, v) for v in vectors]))
        fused = {
            i: sum(1.0 / (self._k + ranking[i]) for ranking in rankings if i in ranking)
            for i in allowed
        }
        best = sorted(allowed, key=lambda i: (-fused[i], i))[: query.limit]
        return tuple(
            RetrievedChunk(
                chunk=self._index.chunks[i],
                fused_score=fused[i],
                bm25_rank=rankings[0].get(i),
                dense_rank=rankings[1].get(i) if len(rankings) > 1 else None,
            )
            for i in best
            if fused[i] > 0
        )


def _ranks(allowed: list[int], scores: list[float] | tuple[float, ...]) -> dict[int, int]:
    """1-based rank among allowed chunks with a positive score; unscored chunks are absent."""
    scored = sorted((i for i in allowed if scores[i] > 0), key=lambda i: (-scores[i], i))
    return {i: rank for rank, i in enumerate(scored, start=1)}


def _cosine(a: Vector, b: Vector) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = sqrt(sum(x * x for x in a)) * sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0
