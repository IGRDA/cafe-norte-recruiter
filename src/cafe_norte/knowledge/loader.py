"""Markdown front matter to ``Document``; headings to ``Chunk``."""

from pathlib import Path

from cafe_norte.knowledge.contracts import Chunk, Document


def load_documents(directory: Path) -> tuple[Document, ...]:
    """Parse every ``*.md`` with front matter; fail on a missing field or duplicate id."""
    raise NotImplementedError


def chunk_document(document: Document, *, max_tokens: int) -> tuple[Chunk, ...]:
    """Split by heading, then by paragraph when a section exceeds the embedding limit."""
    raise NotImplementedError
