"""Build and load the versioned index artifact."""

from pathlib import Path

from cafe_norte.knowledge.contracts import Chunk, Embedder, IndexManifest


async def build_index(chunks: tuple[Chunk, ...], embedder: Embedder, out: Path) -> IndexManifest:
    """Write BM25 tokens, dense vectors and the manifest under ``out/<kb_version>/``."""
    raise NotImplementedError


def load_manifest(directory: Path) -> IndexManifest:
    raise NotImplementedError
