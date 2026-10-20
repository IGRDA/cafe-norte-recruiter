"""BM25 + dense cosine, reciprocal rank fusion, filtered by store before ranking."""

from pathlib import Path

from cafe_norte.knowledge.contracts import (
    Embedder,
    IndexManifest,
    RetrievalQuery,
    RetrievedChunk,
)


class HybridRetriever:
    def __init__(self, artifact: Path, embedder: Embedder, *, rrf_k: int = 60) -> None:
        raise NotImplementedError

    @property
    def manifest(self) -> IndexManifest:
        raise NotImplementedError

    async def retrieve(self, query: RetrievalQuery) -> tuple[RetrievedChunk, ...]:
        raise NotImplementedError
