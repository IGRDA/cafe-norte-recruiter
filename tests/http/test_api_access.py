"""The shared demo access code: a public URL that spends provider credits needs a gate.

With a code configured, nothing session-related opens until ``POST /api/access`` succeeds;
without one (local, tests) everything stays open as before."""

from fastapi.testclient import TestClient

from cafe_norte.model.contracts import ModelFinished, ModelText
from cafe_norte.model.fake import FakeModel
from tests.support.app import build_test_app

SESSION = {"config_id": "chamberi_barista_v1", "language": "es", "channel": "text"}


def gated_client() -> TestClient:
    model = FakeModel([], fallback=[ModelText(text="Vale."), ModelFinished(reason="stop")])
    return TestClient(build_test_app(model=model, access_code="cafe-2026"))


def test_sessions_need_the_code_once_per_browser() -> None:
    with gated_client() as client:
        assert client.get("/api/runtime").json()["access_required"] is True
        assert client.post("/api/sessions", json=SESSION).status_code == 401

        wrong = client.post("/api/access", json={"code": "latte"})
        assert wrong.status_code == 401 and wrong.json()["code"] == "unauthorized"
        assert client.post("/api/sessions", json=SESSION).status_code == 401

        right = client.post("/api/access", json={"code": "cafe-2026"})
        assert right.status_code == 204
        cookie = right.headers["set-cookie"]
        assert "cafe_norte_access=" in cookie and "HttpOnly" in cookie
        assert "cafe-2026" not in cookie  # the cookie is a signature, never the code
        assert client.post("/api/sessions", json=SESSION).status_code == 201


def test_a_forged_access_cookie_is_refused() -> None:
    with gated_client() as client:
        client.cookies.set("cafe_norte_access", "deadbeef")
        assert client.post("/api/sessions", json=SESSION).status_code == 401


def test_without_a_configured_code_everything_stays_open() -> None:
    model = FakeModel([], fallback=[ModelText(text="Vale."), ModelFinished(reason="stop")])
    with TestClient(build_test_app(model=model)) as client:
        assert client.get("/api/runtime").json()["access_required"] is False
        assert client.post("/api/sessions", json=SESSION).status_code == 201
        assert client.post("/api/access", json={"code": "anything"}).status_code == 204
