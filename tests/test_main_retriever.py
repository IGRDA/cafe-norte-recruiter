"""The composition root picks the retriever from the environment."""

from pathlib import Path

import pytest

from cafe_norte.domain.configuration import load_configurations
from cafe_norte.knowledge.hybrid import HybridRetriever
from cafe_norte.main import _retriever
from tests.support import CONFIG_DIR


def test_lexical_is_the_default_and_needs_no_artifact() -> None:
    retriever, warm_up = _retriever({}, load_configurations(CONFIG_DIR))
    assert isinstance(retriever, HybridRetriever) and warm_up is None
    assert retriever.manifest.embedding_model == "none" and retriever.manifest.chunk_count >= 50


def test_an_unknown_mode_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="lexical or hybrid"):
        _retriever({"CAFE_NORTE_RETRIEVER": "vector"}, load_configurations(CONFIG_DIR))
