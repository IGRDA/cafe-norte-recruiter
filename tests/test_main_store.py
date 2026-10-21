"""The composition root picks the store from the environment without opening it."""

import pytest

from cafe_norte.main import _store
from cafe_norte.persistence.memory import MemoryStore
from cafe_norte.persistence.postgres import PostgresStore

URL = "postgresql://cafe:cafe@localhost:5432/cafe_norte"


def test_memory_unless_a_database_url_is_set() -> None:
    assert isinstance(_store({}, voice_mode="off"), MemoryStore)
    assert isinstance(_store({"CAFE_NORTE_DATABASE_URL": ""}, voice_mode="off"), MemoryStore)
    assert isinstance(_store({"CAFE_NORTE_DATABASE_URL": URL}, voice_mode="off"), PostgresStore)


def test_hosted_voice_on_postgres_waits_for_admission_rows() -> None:
    """Admission is still per process; refusing beats a silent cap that a restart forgets."""
    with pytest.raises(ValueError, match="admission"):
        _store({"CAFE_NORTE_DATABASE_URL": URL}, voice_mode="pipecat")
