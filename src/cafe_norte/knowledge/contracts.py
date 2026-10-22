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
    keywords: tuple[str, ...] = ()  # the document's bilingual search terms
    section: str
    text: str


class IndexManifest(Frozen):
    """Identifies an artifact: everything an evaluation run must record."""

    kb_version: str
    embedding_model: str  # "none" for a lexical-only index
    embedding_revision: str
    chunk_count: int
    document_hashes: dict[str, str]


Vector = tuple[float, ...]


class Index(Frozen):
    """One loaded artifact, shared by every session. ``vectors`` is ``None`` when the index
    is lexical only; otherwise one vector per chunk, same order."""

    manifest: IndexManifest
    chunks: tuple[Chunk, ...]
    vectors: tuple[Vector, ...] | None


class RetrievalQuery(Frozen):
    """One to three phrasings of the same question; rankings of every phrasing are fused."""

    queries: tuple[str, ...] = Field(min_length=1, max_length=3)
    config_id: ConfigId
    kb_version: str
    doc_ids: frozenset[str] | None = None  # structured filter; None means every allowed doc
    limit: int = Field(default=3, ge=1, le=5)


class RetrievedChunk(Frozen):
    chunk: Chunk
    fused_score: float  # reciprocal rank fusion; comparable within one query only
    bm25_rank: int | None
    dense_rank: int | None
    bm25_score: float = 0.0  # raw Okapi score; 0 when no query term occurs
    dense_score: float | None = None  # cosine; None without an embedder


class Embedder(Protocol):
    """Query embedding, run off the audio event loop with bounded concurrency."""

    @property
    def name(self) -> str: ...
    @property
    def revision(self) -> str: ...

    async def embed(self, texts: Sequence[str]) -> tuple[Vector, ...]: ...


class Retriever(Protocol):
    """Filters by configuration and version before ranking; never returns a chunk of another
    store. Returns at most ``query.limit`` chunks, best first, possibly none."""

    @property
    def manifest(self) -> IndexManifest: ...

    async def retrieve(self, query: RetrievalQuery) -> tuple[RetrievedChunk, ...]: ...
