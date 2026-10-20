"""Canned retriever for tests and CI evaluations."""

from collections.abc import Mapping

from cafe_norte.knowledge.contracts import IndexManifest, RetrievalQuery, RetrievedChunk


class FakeRetriever:
    def __init__(
        self, answers: Mapping[str, tuple[RetrievedChunk, ...]], manifest: IndexManifest
    ) -> None:
        raise NotImplementedError

    @property
    def manifest(self) -> IndexManifest:
        raise NotImplementedError

    async def retrieve(self, query: RetrievalQuery) -> tuple[RetrievedChunk, ...]:
        raise NotImplementedError
