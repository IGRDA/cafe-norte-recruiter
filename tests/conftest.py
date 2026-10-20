"""Shared fixtures. Postgres fixtures skip unless CAFE_NORTE_TEST_DATABASE_URL is set."""

import os

import pytest


@pytest.fixture
def test_database_url() -> str:
    url = os.environ.get("CAFE_NORTE_TEST_DATABASE_URL")
    if not url:
        pytest.skip("CAFE_NORTE_TEST_DATABASE_URL not set (make test-db)")
    return url
