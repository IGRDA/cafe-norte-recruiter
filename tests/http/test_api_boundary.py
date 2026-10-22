"""The HTTP boundary: security headers on every response, a body size limit, and validation
errors that never echo what was sent. Offline, through ``TestClient``."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from cafe_norte.api.boundary import MAX_BODY_BYTES
from cafe_norte.model.fake import FakeModel
from tests.support.app import build_test_app

HEADERS = {
    "referrer-policy": "no-referrer",
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
}


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(build_test_app(model=FakeModel([]))) as client:
        yield client


@pytest.mark.parametrize("path", ["/health/live", "/api/configurations", "/", "/nope"])
def test_every_response_carries_the_security_headers(client: TestClient, path: str) -> None:
    response = client.get(path)
    for name, value in HEADERS.items():
        assert response.headers[name] == value
    policy = response.headers["content-security-policy"]
    assert "default-src 'self'" in policy
    assert "frame-ancestors 'none'" in policy


def test_the_page_may_load_dailys_call_machine(client: TestClient) -> None:
    """The hosted call: daily-js runs its call machine with Function(), which default-src
    'self' blocked, so no browser could join a room. Inline scripts stay blocked."""
    policy = client.get("/").headers["content-security-policy"]
    script_src = next(d for d in policy.split("; ") if d.startswith("script-src "))
    assert script_src.split()[1:] == ["'self'", "'unsafe-eval'"]
    assert "https://*.daily.co" in policy  # the bundle is fetched, so connect-src carries it


def test_error_responses_carry_them_too(client: TestClient) -> None:
    response = client.post("/api/sessions", json={"nonsense": True})
    assert response.status_code == 422
    assert response.headers["x-content-type-options"] == "nosniff"


def test_a_declared_oversize_body_is_refused_before_any_route_runs(client: TestClient) -> None:
    response = client.post("/api/access", content=b"x" * (MAX_BODY_BYTES + 1))
    assert response.status_code == 413
    assert response.json()["code"] == "limit_exceeded"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_a_streamed_oversize_body_is_refused_without_a_declared_length(
    client: TestClient,
) -> None:
    def chunks() -> Iterator[bytes]:
        for _ in range(MAX_BODY_BYTES // 1024 + 2):
            yield b"x" * 1024

    response = client.post("/api/access", content=chunks())
    assert response.status_code == 413


def test_a_body_at_the_limit_still_reaches_the_route(client: TestClient) -> None:
    response = client.post("/api/access", content=b"x" * MAX_BODY_BYTES)
    assert response.status_code == 422  # not JSON: the route's validation, not the limit


def test_validation_errors_never_echo_the_body(client: TestClient) -> None:
    secret = "s3cret-demo-code-value"
    response = client.post("/api/sessions", json={"config_id": secret, "language": 7})
    assert response.status_code == 422
    assert secret not in response.text
    assert set(response.json()) == {"code", "message"}
