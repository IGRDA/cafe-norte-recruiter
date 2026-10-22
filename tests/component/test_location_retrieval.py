"""Where the store is: the hosted call's "¿dónde está el establecimiento?" must find the address
section of the candidate's own store, however the place is asked for."""

from pathlib import Path

import pytest

from cafe_norte.knowledge.contracts import RetrievalQuery
from cafe_norte.knowledge.hybrid import HybridRetriever
from cafe_norte.knowledge.index import lexical_index
from cafe_norte.knowledge.loader import load_documents
from tests.support import ROOT
from tests.support.builders import CONFIGS

KB_VERSION = next(iter(CONFIGS.values())).kb_version
RETRIEVER = HybridRetriever(
    lexical_index(load_documents(Path(ROOT / "kb")), kb_version=KB_VERSION), None
)
PHRASINGS = [
    "¿Dónde está el establecimiento?",
    "¿Dónde está la tienda?",
    "¿Cuál es la ubicación de la cafetería?",
    "¿Dónde queda el local?",
    "¿Cómo llego?",
]


@pytest.mark.parametrize("store", ["chamberi", "arganzuela"])
@pytest.mark.parametrize("question", PHRASINGS)
async def test_a_question_about_the_place_finds_the_stores_address(
    store: str, question: str
) -> None:
    config = CONFIGS[f"{store}_barista_v1"]  # type: ignore[index]
    found = await RETRIEVER.retrieve(
        RetrievalQuery(
            config_id=config.config_id,
            kb_version=config.kb_version,
            queries=(question,),
            doc_ids=config.kb_doc_ids,  # what search_knowledge passes
        )
    )
    ids = [r.chunk.chunk_id for r in found]
    assert f"store_{store}#direccion" in ids, ids
