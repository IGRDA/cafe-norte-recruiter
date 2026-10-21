"""Build and load the versioned index artifact, or build one in memory."""

import json
from pathlib import Path

from cafe_norte.knowledge.contracts import Chunk, Document, Embedder, Index, IndexManifest
from cafe_norte.knowledge.loader import chunk_document

MANIFEST, CHUNKS, VECTORS = "manifest.json", "chunks.json", "vectors.json"


def embedding_text(chunk: Chunk) -> str:
    """What a chunk's vector represents: its section in the context of its document."""
    return f"{chunk.title}. {chunk.section}. {chunk.text}"


async def index_from_documents(
    documents: tuple[Document, ...], embedder: Embedder | None, *, kb_version: str
) -> Index:
    """The in-memory index: every chunk, vectors when an embedder is given."""
    chunks = tuple(c for d in documents for c in chunk_document(d))
    vectors = (
        await embedder.embed([embedding_text(c) for c in chunks]) if embedder is not None else None
    )
    manifest = IndexManifest(
        kb_version=kb_version,
        embedding_model=embedder.name if embedder else "none",
        embedding_revision=embedder.revision if embedder else "none",
        chunk_count=len(chunks),
        document_hashes={d.doc_id: d.content_hash for d in documents},
    )
    return Index(manifest=manifest, chunks=chunks, vectors=vectors)


async def build_index(
    documents: tuple[Document, ...], embedder: Embedder, out: Path, *, kb_version: str
) -> IndexManifest:
    """Write ``out/<kb_version>/`` with the manifest, the chunks and their vectors."""
    index = await index_from_documents(documents, embedder, kb_version=kb_version)
    directory = out / kb_version
    directory.mkdir(parents=True, exist_ok=True)
    (directory / MANIFEST).write_text(index.manifest.model_dump_json(indent=2))
    (directory / CHUNKS).write_text(
        json.dumps([c.model_dump(mode="json") for c in index.chunks], ensure_ascii=False)
    )
    (directory / VECTORS).write_text(json.dumps(index.vectors))
    return index.manifest


def load_index(out: Path, *, kb_version: str) -> Index:
    directory = out / kb_version
    manifest = IndexManifest.model_validate_json((directory / MANIFEST).read_text())
    chunks = tuple(Chunk.model_validate(c) for c in json.loads((directory / CHUNKS).read_text()))
    raw = json.loads((directory / VECTORS).read_text())
    vectors = None if raw is None else tuple(tuple(float(x) for x in v) for v in raw)
    if manifest.chunk_count != len(chunks) or (vectors is not None and len(vectors) != len(chunks)):
        raise ValueError(f"{directory}: manifest and files disagree")
    return Index(manifest=manifest, chunks=chunks, vectors=vectors)


def load_manifest(out: Path, *, kb_version: str) -> IndexManifest:
    return IndexManifest.model_validate_json((out / kb_version / MANIFEST).read_text())
