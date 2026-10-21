"""Shared fixtures. Postgres fixtures skip unless CAFE_NORTE_TEST_DATABASE_URL is set."""

import os

import psycopg
import pytest


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
