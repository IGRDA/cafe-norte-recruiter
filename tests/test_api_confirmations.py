"""`POST /api/sessions/{id}/confirmations/{confirmation_id}`: the page's Sí / No on a read-back,
through the same domain rules as a spoken answer. Offline, scripted model."""

from collections.abc import Iterator
from typing import Any, NamedTuple

import pytest
from fastapi.testclient import TestClient

from cafe_norte.api.contracts import SessionSnapshotResponse
from cafe_norte.model.fake import FakeModel
from tests.support import build_test_app
from tests.test_api_tracer import OPENING_EVENTS, create_session, read_turn
from tests.test_runtime import DATE_CALL, WANTS_TOOLS, says


@pytest.fixture
def client() -> Iterator[TestClient]:
    # Turn 1 captures the date and the runtime reads it back; what follows is the model's
    # reply to the button turn.
    model = FakeModel([[DATE_CALL, WANTS_TOOLS], says(""), says("Perfecto. ¿Qué experiencia?")])
    with TestClient(build_test_app(model=model)) as client:
        yield client


def snapshot(client: TestClient, session_id: str) -> SessionSnapshotResponse:
    response = client.get(f"/api/sessions/{session_id}")
    assert response.status_code == 200, response.text
    return SessionSnapshotResponse.model_validate_json(response.text)


class ReadBack(NamedTuple):
    session_id: str
    confirmation_id: str
    revision: int
    last_seq: int


def with_read_back(client: TestClient) -> ReadBack:
    """A session with a pending read-back, as the page would see it in a snapshot."""
    session_id = create_session(client)
    client.post(
        f"/api/sessions/{session_id}/turns",
        json={"input_id": "in-1", "text": "El 2 de noviembre"},
    )
    read_turn(client, session_id, after=OPENING_EVENTS)
    seen = snapshot(client, session_id)
    assert seen.state.pending_confirmation is not None
    return ReadBack(
        session_id,
        seen.state.pending_confirmation.confirmation_id,
        seen.state.candidate.revision,
        seen.last_seq,
    )


def answer(client: TestClient, session_id: str, confirmation_id: str, **body: Any) -> Any:
    payload = {"input_id": "btn-1", "answer": "affirm", "expected_revision": 1, **body}
    return client.post(f"/api/sessions/{session_id}/confirmations/{confirmation_id}", json=payload)


def test_the_yes_button_confirms_the_read_back(client: TestClient) -> None:
    session_id, confirmation_id, revision, last_seq = with_read_back(client)

    response = answer(client, session_id, confirmation_id, expected_revision=revision)
    assert response.status_code == 202, response.text
    assert response.json() == {"input_id": "btn-1"}

    events = read_turn(client, session_id, after=last_seq)
    assert [e["data"]["payload"]["name"] for e in events if e["type"] == "tool_started"] == [
        "confirm_field"
    ]
    state = snapshot(client, session_id).state
    assert state.candidate.earliest_start_date.status == "confirmed"
    assert state.pending_confirmation is not None
    assert state.pending_confirmation.status == "confirmed"


def test_the_no_button_rejects_it(client: TestClient) -> None:
    session_id, confirmation_id, revision, last_seq = with_read_back(client)
    response = answer(
        client, session_id, confirmation_id, answer="deny", expected_revision=revision
    )
    assert response.status_code == 202, response.text
    read_turn(client, session_id, after=last_seq)
    pending = snapshot(client, session_id).state.pending_confirmation
    assert pending is not None and pending.status == "rejected"


def test_a_stale_revision_is_a_conflict_and_nothing_runs(client: TestClient) -> None:
    session_id, confirmation_id, revision, last_seq = with_read_back(client)
    response = answer(client, session_id, confirmation_id, expected_revision=revision + 1)
    assert response.status_code == 409
    assert response.json()["code"] == "conflict"
    pending = snapshot(client, session_id).state.pending_confirmation
    assert pending is not None and pending.status == "pending"


def test_a_read_back_that_is_not_the_pending_one_is_not_found(client: TestClient) -> None:
    session_id, _, revision, _ = with_read_back(client)
    response = answer(client, session_id, "an-older-one", expected_revision=revision)
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_an_answered_read_back_cannot_be_answered_again(client: TestClient) -> None:
    session_id, confirmation_id, revision, last_seq = with_read_back(client)
    first = answer(client, session_id, confirmation_id, expected_revision=revision)
    assert first.status_code == 202
    read_turn(client, session_id, after=last_seq)
    again = answer(
        client, session_id, confirmation_id, input_id="btn-2", expected_revision=revision
    )
    assert again.status_code == 409


def test_nobody_else_answers_for_the_candidate(client: TestClient) -> None:
    session_id, confirmation_id, revision, last_seq = with_read_back(client)
    assert answer(client, "0" * 32, confirmation_id).status_code == 401
    client.cookies.clear()
    response = answer(client, session_id, confirmation_id, expected_revision=revision)
    assert response.status_code == 401


def test_only_yes_or_no_is_accepted(client: TestClient) -> None:
    session_id, confirmation_id, revision, last_seq = with_read_back(client)
    response = answer(
        client, session_id, confirmation_id, answer="maybe", expected_revision=revision
    )
    assert response.status_code == 422
    assert "maybe" not in response.text
