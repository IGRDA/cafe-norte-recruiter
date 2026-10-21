"""Shared fixtures. Postgres fixtures skip unless CAFE_NORTE_TEST_DATABASE_URL is set."""

import os
from collections.abc import AsyncIterator

import psycopg
import pytest

from cafe_norte.persistence.contracts import Store
from cafe_norte.persistence.memory import MemoryStore

# The store contract runs against every implementation. ``make check`` runs the memory
# parameter (pytest's addopts deselects ``postgres``); ``make test-db`` runs the other.
STORES = ["memory"]


@pytest.fixture
def test_database_url() -> str:
    url = os.environ.get("CAFE_NORTE_TEST_DATABASE_URL")
    if not url:
        pytest.skip("CAFE_NORTE_TEST_DATABASE_URL not set (make test-db)")
    return url


@pytest.fixture
def empty_database(test_database_url: str) -> str:
    """The test database with no tables at all: what a first deploy sees."""
    with psycopg.connect(test_database_url, autocommit=True) as conn:
        conn.execute("drop schema public cascade; create schema public")
    return test_database_url


@pytest.fixture(params=STORES)
async def store(request: pytest.FixtureRequest) -> AsyncIterator[Store]:
    """A fresh store of the requested kind, empty before every test."""
    if request.param == "memory":
        yield MemoryStore()
        return
    raise NotImplementedError(request.param)
