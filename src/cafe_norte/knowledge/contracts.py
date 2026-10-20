"""Knowledge types and ports."""

from collections.abc import Sequence
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from cafe_norte.domain.contracts import ConfigId
from cafe_norte.errors import Language


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Document(Frozen):
    doc_id: str
    version: str
    config_ids: frozenset[ConfigId]  # shared documents list both
    language: Language
    title: str
    keywords: tuple[str, ...] = ()  # bilingual search terms
    content_hash: str
    body: str


class Chunk(Frozen):
    chunk_id: str  # f"{doc_id}#{section_slug}"
    doc_id: str
    config_ids: frozenset[ConfigId]
    title: str
    section: str
    text: str


class IndexManifest(Frozen):
    """Identifies an artifact: everything an evaluation run must record."""

    kb_version: str
    embedding_model: str
    embedding_revision: str
    chunk_count: int
    document_hashes: dict[str, str]


class RetrievalQuery(Frozen):
    text: str
    config_id: ConfigId
    kb_version: str
    limit: int = Field(default=3, ge=1, le=5)


class RetrievedChunk(Frozen):
    chunk: Chunk
    fused_score: float
    bm25_rank: int | None
    dense_rank: int | None


class Embedder(Protocol):
    """Query embedding, run off the audio event loop with bounded concurrency."""

    async def embed(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]: ...


class Retriever(Protocol):
    """Filters by configuration and version before ranking; never returns a chunk of another
    store. Returns at most ``query.limit`` chunks, best first, possibly none."""

    @property
    def manifest(self) -> IndexManifest: ...

    async def retrieve(self, query: RetrievalQuery) -> tuple[RetrievedChunk, ...]: ...
