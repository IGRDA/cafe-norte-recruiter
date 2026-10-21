"""The export endpoint: the owner downloads their session as JSON; nobody else gets it."""

from fastapi.testclient import TestClient

from cafe_norte.model.fake import FakeModel
from cafe_norte.persistence.export import ExportDocument
from tests.support import build_test_app
from tests.test_api_tracer import ANSWER_TURN, OPENING_EVENTS, TOOL_TURN, create_session, read_turn


def test_the_owner_downloads_the_session_as_json() -> None:
    with TestClient(build_test_app(model=FakeModel([TOOL_TURN, ANSWER_TURN]))) as client:
        session_id = create_session(client)
        client.post(
            f"/api/sessions/{session_id}/turns",
            json={"input_id": "in-1", "text": "Me llamo Lucía Marín"},
        )
        read_turn(client, session_id, after=OPENING_EVENTS)

        response = client.get(f"/api/sessions/{session_id}/export")
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("application/json")
        assert (
            response.headers["content-disposition"] == f'attachment; filename="{session_id}.json"'
        )
        document = ExportDocument.model_validate_json(response.text)
        assert document.session.session_id == session_id
        assert document.session.ended_at is None and document.session.lifecycle == "active"
        assert document.candidate.name.status == "captured"
        assert [t.role for t in document.transcript] == ["assistant", "user", "assistant"]
        assert document.metrics.usage[0].quantity == 120
        assert document.versions.commit_sha == "test"
        assert "test-secret" not in response.text


def test_without_the_session_cookie_there_is_no_export() -> None:
    with TestClient(build_test_app(model=FakeModel([]))) as client:
        session_id = create_session(client)
        other = client.get(f"/api/sessions/{'0' * 32}/export")
        assert other.status_code == 401
        client.cookies.clear()
        assert client.get(f"/api/sessions/{session_id}/export").status_code == 401
