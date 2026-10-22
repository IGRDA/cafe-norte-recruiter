"""The shared demo access code: a public URL that spends provider credits needs a gate.

With a code configured, nothing session-related opens until ``POST /api/access`` succeeds;
without one (local, tests) everything stays open as before."""

import asyncio
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from cafe_norte.api.limits import RequestLimits
from cafe_norte.domain.contracts import SessionId
from cafe_norte.model.contracts import ModelFinished, ModelText
from cafe_norte.model.fake import FakeModel
from cafe_norte.persistence.memory import MemoryStore
from tests.support.app import build_test_app
from tests.support.builders import session_state

SESSION = {"config_id": "chamberi_barista_v1", "language": "es", "channel": "text"}


def gated_client(
    limits: RequestLimits | None = None, store: MemoryStore | None = None
) -> TestClient:
    model = FakeModel([], fallback=[ModelText(text="Vale."), ModelFinished(reason="stop")])
    return TestClient(
        build_test_app(model=model, access_code="cafe-2026", request_limits=limits, store=store)
    )


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


def test_guessing_the_code_is_refused_once_the_attempts_per_minute_are_used() -> None:
    with gated_client(RequestLimits(access_attempts_per_minute=3)) as client:
        wrong = [client.post("/api/access", json={"code": "latte"}).status_code for _ in range(3)]
        assert wrong == [401, 401, 401]

        refused = client.post("/api/access", json={"code": "cafe-2026"})  # even the right one

        assert refused.status_code == 429 and refused.json()["code"] == "rate_limited"
        assert "set-cookie" not in refused.headers


def test_one_client_starts_at_most_its_sessions_per_hour() -> None:
    with gated_client(RequestLimits(session_starts_per_hour=2)) as client:
        client.post("/api/access", json={"code": "cafe-2026"})
        started = [client.post("/api/sessions", json=SESSION).status_code for _ in range(2)]
        assert started == [201, 201]

        refused = client.post("/api/sessions", json=SESSION)

        assert refused.status_code == 429 and refused.json()["code"] == "rate_limited"


def test_no_session_starts_once_the_day_holds_its_sessions_whoever_asks() -> None:
    store = MemoryStore()
    # One older than a day and one within it, started by someone else.
    asyncio.run(_seed(store, (timedelta(hours=25), timedelta(hours=2))))
    with gated_client(RequestLimits(sessions_per_day=2), store=store) as client:
        client.post("/api/access", json={"code": "cafe-2026"})
        assert client.post("/api/sessions", json=SESSION).status_code == 201

        refused = client.post("/api/sessions", json=SESSION)

        assert refused.status_code == 503 and refused.json()["code"] == "busy"


async def _seed(store: MemoryStore, ages: tuple[timedelta, ...]) -> None:
    now = datetime.now(UTC)
    for n, age in enumerate(ages):
        await store.sessions.create(
            session_state(SessionId(f"seed-{n}"), created_at=now - age), access_hash=""
        )
