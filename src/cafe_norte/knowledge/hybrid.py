"""BM25 + dense cosine, reciprocal rank fusion, filtered by store before ranking."""

import re

import numpy as np
import numpy.typing as npt

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
# The relevance floor: a chunk no query word occurs in, whose cosine is below this, is
# noise. Chosen from evals/results/retrieval/: every answerable chunk without a lexical match
# scored ≥ 0.40; the unsupported questions with no lexical match scored ≤ 0.37. Re-measure
# when the embedding model changes.
DENSE_FLOOR = 0.40
# Words nearly every chunk shares: the brand, the city and the role. The configuration already
# names the store, so in a query they only pull the company and role sections up. The store's
# own name stays: an address question needs it. Measured on the model's queries of the gpt-4.1
# baseline: 30/32 answerable questions found, against 26 with its own topic filter.
SHARED_WORDS = re.compile(r"\b(?:caf[eé]\s+norte|madrid|baristas?)\b", re.IGNORECASE)


def searchable(phrasing: str) -> str:
    """The phrasing without the words every document shares; unchanged if nothing else is
    left."""
    return " ".join(SHARED_WORDS.sub(" ", phrasing).split()) or phrasing


def lexical_text(chunk: Chunk) -> str:
    """What BM25 sees: title, keywords, section and text. The bilingual title and keywords
    give English questions lexical hits on Spanish chunks."""
    return f"{chunk.title} {' '.join(chunk.keywords)} {chunk.section} {chunk.text}"


class HybridRetriever:
    """Allowed chunks are those of the query's configuration, KB version and, when given,
    document ids; both rankers rank among allowed chunks only, so a chunk of another store
    can never outrank anything. Without an embedder the retriever is BM25 only."""

    def __init__(
        self,
        index: Index,
        embedder: Embedder | None,
        *,
        rrf_k: int = RRF_K,
        dense_floor: float = DENSE_FLOOR,
    ) -> None:
        if embedder is not None and index.vectors is None:
            raise ValueError("an embedder needs an index with vectors")
        self._index = index
        self._embedder = embedder
        self._k = rrf_k
        self._floor = dense_floor
        self._bm25 = BM25(tuple(tokenize(lexical_text(c)) for c in index.chunks))
        # Unit chunk vectors, one row each: a query's cosines are one matrix product.
        self._unit = _unit_rows(index.vectors) if index.vectors is not None else None

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
        # One BM25 ranking per phrasing, one dense ranking per phrasing (one batched embed
        # call), all fused by reciprocal rank. The raw scores kept per chunk are its best.
        phrasings = [searchable(text) for text in query.queries]
        lexical = [self._bm25.scores(tokenize(text)) for text in phrasings]
        rankings = [_ranks(allowed, scores) for scores in lexical]
        bm25_scores = [max(scores[i] for scores in lexical) for i in range(len(self._index.chunks))]
        dense_scores: list[float] | None = None
        dense_rankings: list[dict[int, int]] = []
        if self._embedder is not None and self._unit is not None:
            vectors = await self._embedder.embed(phrasings)
            cosines = _unit_rows(vectors) @ self._unit.T
            dense_rankings = [_ranks(allowed, scores) for scores in cosines.tolist()]
            dense_scores = cosines.max(axis=0).tolist()
        fused = {
            i: sum(
                1.0 / (self._k + ranking[i])
                for ranking in (*rankings, *dense_rankings)
                if i in ranking
            )
            for i in allowed
        }
        best = sorted(allowed, key=lambda i: (-fused[i], i))[: query.limit]
        return tuple(
            RetrievedChunk(
                chunk=self._index.chunks[i],
                fused_score=fused[i],
                bm25_rank=_best_rank(rankings, i),
                dense_rank=_best_rank(dense_rankings, i) if dense_rankings else None,
                bm25_score=bm25_scores[i],
                dense_score=dense_scores[i] if dense_scores is not None else None,
            )
            for i in best
            if fused[i] > 0 and self._relevant(bm25_scores[i], dense_scores, i)
        )

    def _relevant(self, bm25_score: float, dense_scores: list[float] | None, i: int) -> bool:
        """Lexical overlap is evidence; without it the cosine must clear the floor."""
        if bm25_score > 0 or dense_scores is None:
            return True
        return dense_scores[i] >= self._floor


def _best_rank(rankings: list[dict[int, int]], i: int) -> int | None:
    ranks = [r[i] for r in rankings if i in r]
    return min(ranks) if ranks else None


def _ranks(allowed: list[int], scores: list[float] | tuple[float, ...]) -> dict[int, int]:
    """1-based rank among allowed chunks with a positive score; unscored chunks are absent."""
    scored = sorted((i for i in allowed if scores[i] > 0), key=lambda i: (-scores[i], i))
    return {i: rank for rank, i in enumerate(scored, start=1)}


def _unit_rows(vectors: tuple[Vector, ...]) -> npt.NDArray[np.float64]:
    """Each vector scaled to length one; a zero vector stays zero, so its cosine is 0."""
    rows = np.asarray(vectors, dtype=np.float64)
    norms = np.linalg.norm(rows, axis=1, keepdims=True)
    return np.divide(rows, norms, out=np.zeros_like(rows), where=norms > 0)
