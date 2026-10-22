"""Driving the app over HTTP: create a session, read one turn of server-sent events."""

import json
from typing import Any

from fastapi.testclient import TestClient

from cafe_norte.model.contracts import ModelEvent, ModelFinished, ModelText, ModelUsage, ToolCall

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
