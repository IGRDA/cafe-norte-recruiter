"""`GET /api/sessions/{id}`: the owner's snapshot, and the versions in the create reply."""

from fastapi.testclient import TestClient

from cafe_norte.api.contracts import CreateSessionResponse, SessionSnapshotResponse
from cafe_norte.model.fake import FakeModel
from tests.support import build_test_app
from tests.test_api_tracer import ANSWER_TURN, OPENING_EVENTS, TOOL_TURN, create_session, read_turn


def test_the_owner_reads_state_transcript_versions_and_the_last_sequence() -> None:
    with TestClient(build_test_app(model=FakeModel([TOOL_TURN, ANSWER_TURN]))) as client:
        session_id = create_session(client)
        client.post(
            f"/api/sessions/{session_id}/turns",
            json={"input_id": "in-1", "text": "Me llamo Lucía Marín"},
        )
        events = read_turn(client, session_id, after=OPENING_EVENTS)

        response = client.get(f"/api/sessions/{session_id}")
        assert response.status_code == 200, response.text
        snapshot = SessionSnapshotResponse.model_validate_json(response.text)
        assert snapshot.session_id == session_id
        assert snapshot.state.candidate.name.status == "captured"
        assert [t.role for t in snapshot.transcript] == ["assistant", "user", "assistant"]
        assert snapshot.last_seq == events[-1]["seq"]  # reconnect with Last-Event-ID = last_seq
        assert snapshot.versions.config_id == "chamberi_barista_v1"
        assert snapshot.versions.commit_sha == "test"
        assert "test-secret" not in response.text


def test_nobody_else_reads_it() -> None:
    with TestClient(build_test_app(model=FakeModel([]))) as client:
        session_id = create_session(client)
        assert client.get(f"/api/sessions/{'0' * 32}").status_code == 401
        client.cookies.clear()
        assert client.get(f"/api/sessions/{session_id}").status_code == 401


def test_creating_a_session_returns_the_versions_the_reviewer_panel_shows() -> None:
    with TestClient(build_test_app(model=FakeModel([]))) as client:
        response = client.post(
            "/api/sessions",
            json={"config_id": "arganzuela_barista_v1", "language": "en", "channel": "text"},
        )
        assert response.status_code == 201, response.text
        created = CreateSessionResponse.model_validate_json(response.text)
        assert created.versions.config_id == "arganzuela_barista_v1"
        assert created.versions.prompt_version and created.versions.kb_version
