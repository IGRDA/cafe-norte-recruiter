"""Fakes: a canned retriever keyed by question, and a deterministic embedder for tests."""

from collections.abc import Mapping, Sequence
from math import sqrt

from cafe_norte.knowledge.bm25 import tokenize
from cafe_norte.knowledge.contracts import IndexManifest, RetrievalQuery, RetrievedChunk, Vector

EMPTY_MANIFEST = IndexManifest(
    kb_version="fake",
    embedding_model="none",
    embedding_revision="none",
    chunk_count=0,
    document_hashes={},
)


class FakeRetriever:
    """Answers by the exact first phrasing; anything else retrieves nothing."""

    def __init__(
        self,
        answers: Mapping[str, tuple[RetrievedChunk, ...]] | None = None,
        manifest: IndexManifest = EMPTY_MANIFEST,
    ) -> None:
        self._answers = dict(answers or {})
        self._manifest = manifest
        self.queries: list[RetrievalQuery] = []

    @property
    def manifest(self) -> IndexManifest:
        return self._manifest

    async def retrieve(self, query: RetrievalQuery) -> tuple[RetrievedChunk, ...]:
        self.queries.append(query)
        return self._answers.get(query.queries[0], ())


class FakeEmbedder:
    """Hashed bag of tokens: texts that share words have a higher cosine. Deterministic, no
    model, no network; good enough to exercise fusion, never a measurement."""

    DIMENSIONS = 64

    @property
    def name(self) -> str:
        return "fake-hash-64"

    @property
    def revision(self) -> str:
        return "1"

    async def embed(self, texts: Sequence[str]) -> tuple[Vector, ...]:
        return tuple(self._one(text) for text in texts)

    def _one(self, text: str) -> Vector:
        counts = [0.0] * self.DIMENSIONS
        for token in tokenize(text):
            counts[_stable_hash(token) % self.DIMENSIONS] += 1.0
        norm = sqrt(sum(c * c for c in counts)) or 1.0
        return tuple(c / norm for c in counts)


def _stable_hash(token: str) -> int:
    value = 0
    for char in token:
        value = (value * 131 + ord(char)) % 1_000_003
    return value
