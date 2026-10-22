"""``POST /api/sessions/{id}/voice`` with fake rooms and a fake controller: admission, no
orphan on failure, timings, and what the page learns from ``GET /api/runtime``."""

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from cafe_norte.domain.contracts import SessionId
from cafe_norte.model.contracts import ModelFinished, ModelText
from cafe_norte.model.fake import FakeModel
from cafe_norte.voice.fake import FakeRooms, FakeVoiceController
from tests.support import build_test_app
from tests.test_api_tracer import create_session


@pytest.fixture
def voice() -> FakeVoiceController:
    return FakeVoiceController()


@pytest.fixture
def rooms() -> FakeRooms:
    return FakeRooms()


@pytest.fixture
def client(voice: FakeVoiceController, rooms: FakeRooms) -> Iterator[TestClient]:
    model = FakeModel([], fallback=[ModelText(text="Vale."), ModelFinished(reason="stop")])
    app = build_test_app(model=model, voice_mode="pipecat", rooms=rooms, voice=voice)
    with TestClient(app) as client:
        yield client


def test_runtime_endpoint_tells_the_page_which_voice_to_offer(client: TestClient) -> None:
    body = client.get("/api/runtime").json()
    assert body["voice"] == "pipecat"
    assert "chamberi_barista_v1" in body["config_ids"]


def test_runtime_endpoint_names_the_commit_it_runs(client: TestClient) -> None:
    """The deploy waits for this to be the commit it built: after a reset docker restarts
    the previous release first, and it answers health checks while the new image is pulled."""
    assert client.get("/api/runtime").json()["commit_sha"] == "test"


def test_starting_voice_provisions_a_room_and_starts_the_bot(
    client: TestClient, voice: FakeVoiceController, rooms: FakeRooms
) -> None:
    session_id = create_session(client)
    response = client.post(f"/api/sessions/{session_id}/voice")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["room_url"].startswith("https://") and body["candidate_token"]
    assert "bot_token" not in response.text
    assert voice.started == [session_id]
    assert rooms.created == [session_id] and rooms.destroyed == []
    assert datetime.fromisoformat(body["expires_at"]) > datetime.now(UTC)


def test_starting_voice_twice_for_one_session_is_a_conflict_not_a_second_room(
    client: TestClient, rooms: FakeRooms
) -> None:
    session_id = create_session(client)
    assert client.post(f"/api/sessions/{session_id}/voice").status_code == 200
    again = client.post(f"/api/sessions/{session_id}/voice")
    assert again.status_code == 409 and again.json()["code"] == "conflict"
    assert rooms.created == [session_id]


def test_when_a_voice_session_ends_its_slot_and_room_are_released(
    client: TestClient, voice: FakeVoiceController, rooms: FakeRooms
) -> None:
    """Live: slots leaked after the candidate left the room, and every later start was busy."""
    first, second, third = (create_session(client) for _ in range(3))
    for session_id in (first, second):
        client.cookies.set("cafe_norte_session", cookie_for(client, session_id))
        assert client.post(f"/api/sessions/{session_id}/voice").status_code == 200

    voice.end(SessionId(first))  # the candidate left; the pipeline finished on its own
    client.cookies.set("cafe_norte_session", cookie_for(client, third))
    assert client.post(f"/api/sessions/{third}/voice").status_code == 200
    assert rooms.destroyed == [first]
    # The first session may start voice again: the controller forgot the finished pipeline.
    client.cookies.set("cafe_norte_session", cookie_for(client, first))
    assert client.post(f"/api/sessions/{first}/voice").status_code == 503  # three running now
    voice.end(SessionId(second))
    assert client.post(f"/api/sessions/{first}/voice").status_code == 200


def test_a_third_concurrent_voice_session_is_busy(client: TestClient) -> None:
    """S18 (overload): the third call is refused before a room or a provider is opened."""
    first, second, third = (create_session(client) for _ in range(3))
    # Each create_session replaces the cookie; re-set it per call.
    for session_id in (first, second):
        client.cookies.set("cafe_norte_session", cookie_for(client, session_id))
        assert client.post(f"/api/sessions/{session_id}/voice").status_code == 200
    client.cookies.set("cafe_norte_session", cookie_for(client, third))
    busy = client.post(f"/api/sessions/{third}/voice")
    assert busy.status_code == 503 and busy.json()["code"] == "busy"


def test_a_failed_bot_start_leaves_no_room_and_frees_the_slot(
    client: TestClient, voice: FakeVoiceController, rooms: FakeRooms
) -> None:
    voice.fail_next_start = True
    session_id = create_session(client)
    failed = client.post(f"/api/sessions/{session_id}/voice")
    assert failed.status_code == 503 and failed.json()["code"] == "provider_unavailable"
    assert rooms.destroyed == [session_id]
    # The slot is free again: starting works on the next attempt.
    assert client.post(f"/api/sessions/{session_id}/voice").status_code == 200


def test_browser_timings_are_recorded_as_stage_timings(client: TestClient) -> None:
    session_id = create_session(client)
    client.post(f"/api/sessions/{session_id}/voice")
    response = client.post(
        f"/api/sessions/{session_id}/voice/timings",
        json={"turn_id": None, "event": "connected", "monotonic_ms": 1234},
    )
    assert response.status_code == 204


def test_voice_is_unavailable_when_off() -> None:
    model = FakeModel([], fallback=[ModelText(text="Vale."), ModelFinished(reason="stop")])
    with TestClient(build_test_app(model=model)) as client:
        session_id = create_session(client)
        response = client.post(f"/api/sessions/{session_id}/voice")
        assert response.status_code == 503
        assert response.json()["code"] == "provider_unavailable"
        assert client.get("/api/runtime").json()["voice"] == "off"


def cookie_for(client: TestClient, session_id: str) -> str:
    """The test app's gate signs with a known secret; mint the cookie the way the server does."""
    from cafe_norte.api.access import AccessGate
    from cafe_norte.domain.contracts import SessionId

    return AccessGate(code=None, secret=b"test-secret").issue_session_cookie(SessionId(session_id))
