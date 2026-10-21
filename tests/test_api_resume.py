"""S13 and the resume contract through the HTTP boundary: a private link opens only its own
session, a wrong or expired token opens nothing, a session id alone opens nothing."""

import asyncio
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from cafe_norte.api.access import AccessGate
from cafe_norte.domain.contracts import SessionId
from cafe_norte.model.contracts import ModelFinished, ModelText
from cafe_norte.model.fake import FakeModel
from cafe_norte.persistence.memory import MemoryStore
from tests.support import build_test_app
from tests.test_api_tracer import read_turn

SESSION = {"config_id": "chamberi_barista_v1", "language": "es", "channel": "text"}


def app_and_store() -> tuple[TestClient, MemoryStore]:
    store = MemoryStore()
    model = FakeModel([], fallback=[ModelText(text="Vale."), ModelFinished(reason="stop")])
    return TestClient(build_test_app(model=model, store=store)), store


def test_the_link_reopens_its_own_session_with_a_fresh_browser() -> None:
    client, _ = app_and_store()
    with client:
        created = client.post("/api/sessions", json=SESSION)
        session_id = created.json()["session_id"]
        resume_url = created.json()["resume_url"]
        assert resume_url.startswith("/#resume=") and len(resume_url) > 40
        read_turn(client, session_id)  # the opening
        token = resume_url.split("=", 1)[1]

        fresh = TestClient(client.app)
        with fresh:
            assert fresh.get(f"/api/sessions/{session_id}/events").status_code == 401
            resumed = fresh.post("/api/resume", json={"token": token})
            assert resumed.status_code == 200, resumed.text
            assert resumed.json()["session_id"] == session_id
            assert "cafe_norte_session" in resumed.cookies
            events = read_turn(fresh, session_id)  # replays from the start: the opening...
            assert events[1]["data"]["payload"]["text"].startswith("Hola, soy Ana")
            after = read_turn(fresh, session_id, after=events[-1]["seq"])  # ...then the resume
            assert after[1]["data"]["payload"]["text"].startswith("Hola de nuevo, soy Ana")
            assert (
                fresh.post(
                    f"/api/sessions/{session_id}/turns", json={"input_id": "r1", "text": "Sigo"}
                ).status_code
                == 202
            )


def test_a_wrong_or_expired_token_and_a_guessed_session_id_open_nothing() -> None:
    client, store = app_and_store()
    with client:
        a = client.post("/api/sessions", json=SESSION).json()["session_id"]
        b_token = client.post("/api/sessions", json=SESSION).json()["resume_url"].split("=", 1)[1]
        fresh = TestClient(client.app)
        with fresh:
            assert fresh.post("/api/resume", json={"token": "x" * 43}).status_code == 401
            assert fresh.post("/api/resume", json={"token": "short"}).status_code == 422
            expired_token, expired_hash = AccessGate(code=None, secret=b"x").new_resume_token()
            asyncio.run(
                store.resume_tokens.issue(
                    SessionId(a), expired_hash, expires_at=datetime.now(UTC) - timedelta(days=1)
                )
            )
            assert fresh.post("/api/resume", json={"token": expired_token}).status_code == 401
            # b's link never opens a: the cookie it sets is b's
            assert fresh.post("/api/resume", json={"token": b_token}).status_code == 200
            assert fresh.get(f"/api/sessions/{a}/events").status_code == 401
            assert fresh.get(f"/api/sessions/{a}/export").status_code == 401
