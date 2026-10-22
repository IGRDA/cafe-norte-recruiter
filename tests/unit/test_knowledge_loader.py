"""Front matter to documents, headings to chunks; the real KB obeys the limits and matches
the configurations, which stay the canonical source of hours and shifts."""

import re
from datetime import time
from pathlib import Path

import pytest

from cafe_norte.domain.contracts import ConfigId
from cafe_norte.knowledge.contracts import Chunk, Document
from cafe_norte.knowledge.loader import MAX_CHUNK_WORDS, chunk_document, load_documents, slugify
from tests.support import ROOT
from tests.support.builders import CONFIGS

KB_DIR = ROOT / "kb"
FRONT = """---
doc_id: {doc_id}
version: "1"
config_ids: [chamberi_barista_v1]
language: es
title: T / T
keywords: [a]
---
"""


def write(path: Path, doc_id: str, body: str) -> None:
    path.write_text(FRONT.format(doc_id=doc_id) + body, encoding="utf-8")


def test_slug_strips_accents_punctuation_and_case() -> None:
    assert slugify("¿Hace falta experiencia?") == "hace-falta-experiencia"
    assert slugify("Cómo llegar el día de la entrevista") == "como-llegar-el-dia-de-la-entrevista"


def test_documents_load_with_hash_and_fail_on_duplicates_or_missing_fields(
    tmp_path: Path,
) -> None:
    write(tmp_path / "a.md", "one", "# T\n\n## S\n\ntext")
    (document,) = load_documents(tmp_path)
    assert document.doc_id == "one" and len(document.content_hash) == 64
    assert document.config_ids == frozenset({ConfigId("chamberi_barista_v1")})
    write(tmp_path / "b.md", "one", "# T\n\n## S\n\nother")
    with pytest.raises(ValueError, match="duplicate doc_id"):
        load_documents(tmp_path)
    (tmp_path / "b.md").write_text("---\ndoc_id: two\n---\nbody")
    with pytest.raises(Exception, match="version"):
        load_documents(tmp_path)


def test_sections_become_chunks_and_long_sections_split_by_paragraph() -> None:
    long = "\n\n".join(" ".join(f"w{i}" for i in range(40)) for _ in range(3))
    document = Document(
        doc_id="d",
        version="1",
        config_ids=frozenset({ConfigId("c")}),
        language="es",
        title="Título",
        keywords=(),
        content_hash="x",
        body=f"# Título\n\nintro\n\n## Primera sección\n\ncorto\n\n## Larga\n\n{long}",
    )
    chunks = chunk_document(document, max_words=90)
    assert [c.chunk_id for c in chunks] == ["d#primera-seccion", "d#larga", "d#larga-2"]
    assert chunks[0].section == "Primera sección" and chunks[0].text == "corto"
    assert all(len(c.text.split()) <= 90 for c in chunks)
    assert chunks[1].title == "Título" and chunks[1].doc_id == "d"


# ---- the real knowledge base --------------------------------------------------------------------


def kb_chunks() -> dict[str, tuple[Chunk, ...]]:
    return {d.doc_id: chunk_document(d) for d in load_documents(KB_DIR)}


def test_the_kb_has_twelve_documents_with_unique_short_chunks() -> None:
    documents = load_documents(KB_DIR)
    assert len(documents) == 12
    ids = [c.chunk_id for chunks in kb_chunks().values() for c in chunks]
    assert len(ids) == len(set(ids))
    assert all(not i.endswith("-2") for i in ids), "a KB section exceeds the chunk limit"
    assert all(len(c.text.split()) <= MAX_CHUNK_WORDS for ch in kb_chunks().values() for c in ch)


def test_each_configuration_lists_exactly_the_documents_that_allow_it() -> None:
    documents = load_documents(KB_DIR)
    for configuration in CONFIGS.values():
        allowing = {d.doc_id for d in documents if configuration.config_id in d.config_ids}
        assert allowing == set(configuration.kb_doc_ids), configuration.config_id


def test_offer_and_store_documents_state_the_configured_hours_and_shifts() -> None:
    by_id = {d.doc_id: d for d in load_documents(KB_DIR)}
    for configuration in CONFIGS.values():
        store = configuration.config_id.split("_")[0]
        offer, place = by_id[f"offer_{store}"].body, by_id[f"store_{store}"].body
        assert f"{configuration.hours_per_week} horas" in offer
        opening = _opening_hours(place)
        for shift in configuration.shifts:
            assert f"de {shift.starts} a {shift.ends}" in place, shift.shift_id
            for day in shift.days:
                opens, closes = opening[day]
                assert opens <= time.fromisoformat(shift.starts), (shift.shift_id, day)
                assert time.fromisoformat(shift.ends) <= closes, (shift.shift_id, day)


DAYS = {
    "lunes": "mon",
    "martes": "tue",
    "miércoles": "wed",
    "jueves": "thu",
    "viernes": "fri",
    "sábado": "sat",
    "sábados": "sat",
    "domingo": "sun",
    "domingos": "sun",
}
ORDER = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_RANGE = re.compile(
    r"de (\w+) a (\w+) de (\d\d:\d\d) a (\d\d:\d\d)|los (\w+) y (\w+) de (\d\d:\d\d) a (\d\d:\d\d)"
)


def _opening_hours(body: str) -> dict[str, tuple[time, time]]:
    """Opening hours per weekday from the ``## Horario`` section's two sentence shapes."""
    section = body.split("## Horario", 1)[1].split("## ", 1)[0]
    hours: dict[str, tuple[time, time]] = {}
    for m in _RANGE.finditer(section):
        if m.group(1):
            first, last = ORDER.index(DAYS[m.group(1)]), ORDER.index(DAYS[m.group(2)])
            days, opens, closes = ORDER[first : last + 1], m.group(3), m.group(4)
        else:
            days, opens, closes = [DAYS[m.group(5)], DAYS[m.group(6)]], m.group(7), m.group(8)
        for day in days:
            hours[day] = (time.fromisoformat(opens), time.fromisoformat(closes))
    return hours
