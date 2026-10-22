"""`POST /api/sessions/{id}/end`: the owner finishes the conversation; nobody else can."""

from fastapi.testclient import TestClient

from cafe_norte.api.contracts import SessionSnapshotResponse
from cafe_norte.domain.lifecycle import is_terminal
from cafe_norte.model.fake import FakeModel
from tests.support.app import build_test_app
from tests.support.http import create_session


def snapshot(client: TestClient, session_id: str) -> SessionSnapshotResponse:
    response = client.get(f"/api/sessions/{session_id}")
    assert response.status_code == 200, response.text
    return SessionSnapshotResponse.model_validate_json(response.text)


def test_the_owner_ends_the_session() -> None:
    with TestClient(build_test_app(model=FakeModel([]))) as client:
        session_id = create_session(client)
        assert not is_terminal(snapshot(client, session_id).state)

        response = client.post(f"/api/sessions/{session_id}/end")
        assert response.status_code == 204, response.text

        assert is_terminal(snapshot(client, session_id).state)


def test_ending_twice_is_harmless() -> None:
    with TestClient(build_test_app(model=FakeModel([]))) as client:
        session_id = create_session(client)
        assert client.post(f"/api/sessions/{session_id}/end").status_code == 204
        before = snapshot(client, session_id).state
        assert client.post(f"/api/sessions/{session_id}/end").status_code == 204
        assert snapshot(client, session_id).state == before


def test_nobody_else_ends_it() -> None:
    with TestClient(build_test_app(model=FakeModel([]))) as client:
        session_id = create_session(client)
        assert client.post(f"/api/sessions/{'0' * 32}/end").status_code == 401
        client.cookies.clear()
        assert client.post(f"/api/sessions/{session_id}/end").status_code == 401
