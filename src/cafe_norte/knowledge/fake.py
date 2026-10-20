"""Canned retriever for tests and CI evaluations."""

from collections.abc import Mapping

from cafe_norte.knowledge.contracts import IndexManifest, RetrievalQuery, RetrievedChunk

EMPTY_MANIFEST = IndexManifest(
    kb_version="fake",
    embedding_model="none",
    embedding_revision="none",
    chunk_count=0,
    document_hashes={},
)


class FakeRetriever:
    """Answers by exact query text; anything else retrieves nothing."""

    def __init__(
        self,
        answers: Mapping[str, tuple[RetrievedChunk, ...]] | None = None,
        manifest: IndexManifest = EMPTY_MANIFEST,
    ) -> None:
        self._answers = dict(answers or {})
        self._manifest = manifest

    @property
    def manifest(self) -> IndexManifest:
        return self._manifest

    async def retrieve(self, query: RetrievalQuery) -> tuple[RetrievedChunk, ...]:
        return self._answers.get(query.text, ())
