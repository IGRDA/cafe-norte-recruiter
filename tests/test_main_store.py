"""The composition root picks the store from the environment without opening it."""

from cafe_norte.main import _store
from cafe_norte.persistence.memory import MemoryStore
from cafe_norte.persistence.postgres import PostgresStore

URL = "postgresql://cafe:cafe@localhost:5432/cafe_norte"


def test_memory_unless_a_database_url_is_set() -> None:
    assert isinstance(_store({}), MemoryStore)
    assert isinstance(_store({"CAFE_NORTE_DATABASE_URL": ""}), MemoryStore)
    assert isinstance(_store({"CAFE_NORTE_DATABASE_URL": URL}), PostgresStore)


def test_hosted_voice_runs_on_postgres_too() -> None:
    assert isinstance(_store({"CAFE_NORTE_DATABASE_URL": URL}), PostgresStore)
