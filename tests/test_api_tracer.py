"""Acceptance test of the first tracer bullet, through the HTTP boundary.

Given a session, when the candidate says their name and the model calls ``update_candidate``,
the browser sees: turn started, tool started and finished, state updated with the captured
name, the answer sentence by sentence, turn finished. All offline, scripted model, memory store.
"""

import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from cafe_norte.model.contracts import ModelEvent, ModelFinished, ModelText, ModelUsage, ToolCall
from cafe_norte.model.fake import FakeModel
from tests.support import build_test_app

NAME_CALL = ToolCall(
    call_id="call_1",
    name="update_candidate",
    arguments_json=json.dumps(
        {"patch": {"name": "Lucía Marín"}, "evidence_text": "Me llamo Lucía Marín"}
    ),
)
TOOL_TURN: list[ModelEvent] = [
    NAME_CALL,
    ModelUsage(input_tokens=120, output_tokens=9, model_id="fake"),
    ModelFinished(reason="tool_calls"),
]
ANSWER_TURN: list[ModelEvent] = [
    ModelText(text="Encantada, Lucía. "),
    ModelText(text="¿Te interesa el puesto de barista?"),
    ModelUsage(input_tokens=120, output_tokens=14, model_id="fake"),
    ModelFinished(reason="stop"),
]


def read_turn(client: TestClient, session_id: str, *, after: int = 0) -> list[dict[str, Any]]:
    """Collect SSE events for one turn: everything until ``turn_finished`` or ``turn_failed``."""
    headers = {"Last-Event-ID": str(after)} if after else {}
    seen: list[dict[str, Any]] = []
    with client.stream("GET", f"/api/sessions/{session_id}/events", headers=headers) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        event: dict[str, Any] = {}
        for line in response.iter_lines():
            if line.startswith("id: "):
                event["seq"] = int(line[4:])
            elif line.startswith("event: "):
                event["type"] = line[7:]
            elif line.startswith("data: "):
                event["data"] = json.loads(line[6:])
            elif line == "" and event:
                seen.append(event)
                if event["type"] in {"turn_finished", "turn_failed"}:
                    return seen
                event = {}
    return seen


@pytest.fixture
def model() -> FakeModel:
    return FakeModel([TOOL_TURN, ANSWER_TURN])


@pytest.fixture
def client(model: FakeModel) -> Iterator[TestClient]:
    with TestClient(build_test_app(model=model)) as client:
        yield client


def create_session(client: TestClient) -> str:
    response = client.post(
        "/api/sessions",
        json={"config_id": "chamberi_barista_v1", "language": "es", "channel": "text"},
    )
    assert response.status_code == 201, response.text
    assert "cafe_norte_session" in response.cookies
    session_id = str(response.json()["session_id"])
    opening = read_turn(client, session_id)
    assert [e["type"] for e in opening] == ["turn_started", "assistant_text", "turn_finished"]
    assert opening[0]["data"]["payload"]["text"] == ""  # Ana opens; nobody spoke yet
    assert opening[1]["data"]["payload"]["text"].startswith("Hola, soy Ana, la asistente de IA")
    return session_id


OPENING_EVENTS = 3


def test_a_name_is_captured_persisted_and_then_announced(
    client: TestClient, model: FakeModel
) -> None:
    session_id = create_session(client)

    accepted = client.post(
        f"/api/sessions/{session_id}/turns",
        json={"input_id": "in-1", "text": "Me llamo Lucía Marín"},
    )
    assert accepted.status_code == 202

    events = read_turn(client, session_id, after=OPENING_EVENTS)
    types = [e["type"] for e in events]
    assert types == [
        "turn_started",
        "tool_started",
        "state_updated",
        "tool_finished",
        "assistant_text",
        "assistant_text",
        "turn_finished",
    ]
    assert [e["seq"] for e in events] == list(range(OPENING_EVENTS + 1, OPENING_EVENTS + 8))
    # The stream carries the user's words, so the page renders from the stream alone.
    assert events[0]["data"]["payload"]["text"] == "Me llamo Lucía Marín"

    state = events[2]["data"]["payload"]
    assert state["revision"] == 1
    assert state["candidate"]["name"] == {
        "status": "captured",
        "value": "Lucía Marín",
        "evidence": {
            "source_turn_id": events[0]["data"]["turn_id"],
            "text": "Me llamo Lucía Marín",
        },
    }
    assert [e["data"]["payload"]["text"] for e in events[4:6]] == [
        "Encantada, Lucía.",
        "¿Te interesa el puesto de barista?",
    ]
    finished = events[6]["data"]["payload"]
    assert finished["interrupted"] is False
    assert finished["usage"][0]["quantity"] == 120

    # The model saw the tool result and the user text in order; prompt assembly is real.
    second_call = model.calls[1]
    assert [m.role for m in second_call] == ["system", "assistant", "user", "assistant", "tool"]
    assert second_call[1].content.startswith("Hola, soy Ana")  # the opening is in the history
    assert second_call[2].content == "Me llamo Lucía Marín"


def test_the_stream_replays_from_last_event_id(client: TestClient) -> None:
    session_id = create_session(client)
    client.post(
        f"/api/sessions/{session_id}/turns", json={"input_id": "in-1", "text": "Me llamo Lucía"}
    )
    read_turn(client, session_id, after=OPENING_EVENTS)

    replayed = read_turn(client, session_id, after=OPENING_EVENTS + 4)
    assert [e["seq"] for e in replayed] == [
        OPENING_EVENTS + 5,
        OPENING_EVENTS + 6,
        OPENING_EVENTS + 7,
    ]


def test_a_resubmitted_input_id_fails_once_with_conflict(client: TestClient) -> None:
    session_id = create_session(client)
    body = {"input_id": "in-1", "text": "Me llamo Lucía"}
    client.post(f"/api/sessions/{session_id}/turns", json=body)
    read_turn(client, session_id, after=OPENING_EVENTS)

    again = client.post(f"/api/sessions/{session_id}/turns", json=body)
    assert again.status_code == 202
    events = read_turn(client, session_id, after=OPENING_EVENTS + 7)
    assert [e["type"] for e in events] == ["turn_failed"]
    assert events[0]["data"]["payload"]["code"] == "conflict"


def test_only_the_owner_can_read_or_write_a_session(client: TestClient) -> None:
    session_id = create_session(client)
    client.cookies.clear()
    assert client.get(f"/api/sessions/{session_id}/events").status_code == 401
    turn = client.post(f"/api/sessions/{session_id}/turns", json={"input_id": "x", "text": "hola"})
    assert turn.status_code == 401
    assert "hola" not in turn.text


def test_validation_errors_never_echo_the_input(client: TestClient) -> None:
    session_id = create_session(client)
    response = client.post(
        f"/api/sessions/{session_id}/turns", json={"input_id": "x", "text": "a" * 2001}
    )
    assert response.status_code == 422
    assert "aaaa" not in response.text


def test_a_turn_after_the_session_ended_fails_on_the_stream_with_session_ended() -> None:
    end = ToolCall(call_id="e1", name="end_session", arguments_json='{"reason": "not_interested"}')
    model = FakeModel(
        [
            [end, ModelFinished(reason="tool_calls")],
            [ModelText(text="Adiós."), ModelFinished(reason="stop")],
        ]
    )
    with TestClient(build_test_app(model=model)) as client:
        session_id = create_session(client)
        client.post(
            f"/api/sessions/{session_id}/turns", json={"input_id": "a", "text": "no me interesa"}
        )
        ended = read_turn(client, session_id, after=OPENING_EVENTS)
        assert ended[-1]["type"] == "turn_finished"
        state = next(e for e in ended if e["type"] == "state_updated")["data"]["payload"]
        assert (state["lifecycle"], state["outcome"]) == ("stopped", "incomplete")
        client.post(f"/api/sessions/{session_id}/turns", json={"input_id": "b", "text": "hola?"})
        refused = read_turn(client, session_id, after=ended[-1]["seq"])
        assert [e["type"] for e in refused] == ["turn_failed"]
        assert refused[0]["data"]["payload"]["code"] == "session_ended"
        assert refused[0]["data"]["payload"]["message"] == "Esta conversación ha terminado."


def test_the_page_and_health_are_served(client: TestClient) -> None:
    assert client.get("/health/live").status_code == 200
    page = client.get("/")
    assert page.status_code == 200
    assert "Café Norte" in page.text
