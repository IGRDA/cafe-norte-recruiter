"""Shared fixtures. Postgres fixtures skip unless CAFE_NORTE_TEST_DATABASE_URL is set."""

import os
from collections.abc import AsyncIterator

import psycopg
import pytest
from hypothesis import settings

from cafe_norte.persistence.contracts import Store
from cafe_norte.persistence.memory import MemoryStore
from cafe_norte.persistence.postgres import PostgresStore

# Property-test effort (D50): ``dev`` by default, ``ci`` in CI (more examples, the same ones
# every run), ``deep`` for ``make quality``. No deadline: these are not timing tests.
settings.register_profile("dev", max_examples=100, deadline=None)
settings.register_profile("ci", max_examples=300, deadline=None, derandomize=True)
settings.register_profile("deep", max_examples=2000, deadline=None)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))

# The store contract runs against every implementation. ``make check`` runs the memory
# parameter (pytest's addopts deselects ``postgres``); ``make test-db`` runs the other.
STORES = ["memory", pytest.param("postgres", marks=pytest.mark.postgres)]
TABLES = "sessions, interview_slots"  # the roots; every other table cascades from them


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
    url = request.getfixturevalue("test_database_url")
    postgres = PostgresStore(url, poll_seconds=0.02)
    await postgres.open()  # applies the migrations when the database is fresh
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(f"truncate {TABLES} restart identity cascade")
    yield postgres
    await postgres.close()
