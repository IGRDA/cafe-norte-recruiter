"""Build the versioned knowledge index into kb/index/<kb_version>/ with FastEmbed.
Needs `uv sync --extra knowledge`; the Docker image runs it at build time."""

import asyncio
import os
from pathlib import Path

from cafe_norte.domain.configuration import load_configurations
from cafe_norte.knowledge.embedder import DEFAULT_MODEL, FastEmbedEmbedder
from cafe_norte.knowledge.index import build_index
from cafe_norte.knowledge.loader import load_documents

ROOT = Path(__file__).resolve().parents[1]


def kb_version(config_dir: Path) -> str:
    versions = {c.kb_version for c in load_configurations(config_dir).values()}
    if len(versions) != 1:
        raise SystemExit(f"configurations disagree on kb_version: {sorted(versions)}")
    return versions.pop()


async def run() -> int:
    env = os.environ
    out = Path(env.get("CAFE_NORTE_KB_INDEX", "kb/index"))
    version = kb_version(Path(env.get("CAFE_NORTE_CONFIG_DIR", "config")))
    documents = load_documents(Path(env.get("CAFE_NORTE_KB_DIR", "kb")))
    embedder = FastEmbedEmbedder(env.get("CAFE_NORTE_EMBEDDING_MODEL", DEFAULT_MODEL))
    manifest = await build_index(documents, embedder, out, kb_version=version)
    print(f"wrote {out / version}: {manifest.chunk_count} chunks, {manifest.embedding_model}")
    return 0


def main() -> int:
    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())
