"""Markdown front matter to ``Document``; ``## `` headings to ``Chunk``."""

import hashlib
import re
import unicodedata
from pathlib import Path

import yaml

from cafe_norte.knowledge.contracts import Chunk, Document

MAX_CHUNK_WORDS = 90  # under the 128-token limit of paraphrase-multilingual-MiniLM-L12-v2

_FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)
_SECTION = re.compile(r"^## +(.+?)\s*$", re.MULTILINE)
_NON_SLUG = re.compile(r"[^a-z0-9]+")


def load_documents(directory: Path) -> tuple[Document, ...]:
    """Parse every ``*.md`` with front matter; fail on a missing field or duplicate id."""
    documents: dict[str, Document] = {}
    for path in sorted(p for p in directory.glob("*.md") if p.name != "README.md"):
        match = _FRONT_MATTER.match(path.read_text(encoding="utf-8"))
        if match is None:
            raise ValueError(f"{path.name}: no front matter")
        meta = yaml.safe_load(match.group(1))
        body = match.group(2).strip()
        document = Document(
            **meta,
            content_hash=hashlib.sha256(body.encode("utf-8")).hexdigest(),
            body=body,
        )
        if document.doc_id in documents:
            raise ValueError(f"{path.name}: duplicate doc_id {document.doc_id}")
        documents[document.doc_id] = document
    return tuple(documents.values())


def chunk_document(document: Document, *, max_words: int = MAX_CHUNK_WORDS) -> tuple[Chunk, ...]:
    """One chunk per ``## `` section, ``doc_id#slug``; a section over ``max_words`` splits by
    paragraph into ``#slug-2``, ``#slug-3``… Text before the first section (the title) is
    not a chunk."""
    chunks: list[Chunk] = []
    parts = _SECTION.split(document.body)
    for heading, text in zip(parts[1::2], parts[2::2], strict=True):
        slug = slugify(heading)
        pieces = _split(text.strip(), max_words)
        for n, piece in enumerate(pieces, start=1):
            suffix = "" if n == 1 else f"-{n}"
            chunks.append(
                Chunk(
                    chunk_id=f"{document.doc_id}#{slug}{suffix}",
                    doc_id=document.doc_id,
                    config_ids=document.config_ids,
                    title=document.title,
                    keywords=document.keywords,
                    section=heading.strip(),
                    text=piece,
                )
            )
    return tuple(chunks)


def slugify(heading: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", heading).encode("ascii", "ignore").decode()
    return _NON_SLUG.sub("-", ascii_text.lower()).strip("-")


def _split(text: str, max_words: int) -> list[str]:
    """Whole text when it fits; otherwise paragraphs packed greedily under ``max_words``."""
    if len(text.split()) <= max_words:
        return [text]
    pieces: list[str] = []
    current: list[str] = []
    for paragraph in re.split(r"\n\s*\n", text):
        candidate = [*current, paragraph]
        if current and len(" ".join(candidate).split()) > max_words:
            pieces.append("\n\n".join(current))
            current = [paragraph]
        else:
            current = candidate
    if current:
        pieces.append("\n\n".join(current))
    return pieces
