"""The 24 retrieval questions have the shape the spec asks for; the sections they expect exist."""

from collections import Counter

import yaml
from evals.contracts import RetrievalCase

from cafe_norte.knowledge.loader import chunk_document, load_documents
from tests.support import ROOT

FIXTURE = ROOT / "evals" / "cases" / "retrieval" / "questions.yaml"


def cases() -> tuple[RetrievalCase, ...]:
    return tuple(RetrievalCase.model_validate(c) for c in yaml.safe_load(FIXTURE.read_text()))


def test_the_fixture_is_16_answerable_4_unsupported_4_leakage_and_balanced() -> None:
    loaded = cases()
    assert len({c.id for c in loaded}) == 24
    kinds = Counter(c.kind for c in loaded)
    assert kinds == {"answerable": 16, "unsupported": 4, "leakage": 4}
    cells = Counter((c.language, c.config_id) for c in loaded if c.kind == "answerable")
    assert set(cells.values()) == {4}, cells
    for c in loaded:
        if c.kind == "answerable":
            assert c.expected_sections and c.expected_facts, c.id
        else:
            assert not c.expected_sections, c.id


def test_every_expected_section_exists_in_the_configured_documents() -> None:
    chunk_ids = {c.chunk_id for d in load_documents(ROOT / "kb") for c in chunk_document(d)}
    for case in cases():
        for section in case.expected_sections:
            assert section in chunk_ids, f"{case.id}: {section}"
