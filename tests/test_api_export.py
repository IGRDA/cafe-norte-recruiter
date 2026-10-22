"""The export endpoint: the owner downloads their session as JSON; nobody else gets it."""

import asyncio
from datetime import UTC, datetime
from functools import partial

import pytest
from fastapi.testclient import TestClient

from cafe_norte.domain.contracts import SessionId
from cafe_norte.model.contracts import ModelFinished, ModelText, ModelUsage, ToolCall
from cafe_norte.model.fake import FakeModel
from cafe_norte.observability.contracts import Price, PriceTable
from cafe_norte.observability.cost import estimate
from cafe_norte.persistence.export import ExportDocument
from cafe_norte.persistence.memory import MemoryStore
from tests.support.app import build_test_app
from tests.support.http import ANSWER_TURN, OPENING_EVENTS, TOOL_TURN, create_session, read_turn

PRICED = partial(
    estimate,
    prices=PriceTable(
        version="test",
        verified_on=datetime(2026, 10, 21, tzinfo=UTC),
        prices=(
            Price(kind="llm_tokens", unit_detail="fake:input", eur_per_unit=0.001),
            Price(kind="llm_tokens", unit_detail="fake:output", eur_per_unit=0.01),
        ),
    ),
)


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


def test_a_closed_session_is_served_from_the_stored_snapshot() -> None:
    end = ToolCall(call_id="e1", name="end_session", arguments_json='{"reason": "not_interested"}')
    model = FakeModel(
        [
            [end, ModelFinished(reason="tool_calls")],
            [ModelText(text="Adiós."), ModelFinished(reason="stop")],
        ]
    )
    store = MemoryStore()
    with TestClient(build_test_app(model=model, store=store)) as client:
        session_id = create_session(client)
        client.post(f"/api/sessions/{session_id}/turns", json={"input_id": "a", "text": "no"})
        read_turn(client, session_id, after=OPENING_EVENTS)
        stored = asyncio.run(store.exports.read_snapshot(SessionId(session_id)))
        assert stored is not None
        document = ExportDocument.model_validate_json(stored)
        assert document.session.lifecycle == "stopped" and document.session.ended_at is not None
        response = client.get(f"/api/sessions/{session_id}/export")
        assert response.status_code == 200 and response.text == stored


def test_the_owner_deletes_the_session_and_nothing_of_it_remains() -> None:
    store = MemoryStore()
    with TestClient(
        build_test_app(model=FakeModel([TOOL_TURN, ANSWER_TURN]), store=store)
    ) as client:
        session_id = create_session(client)
        client.post(f"/api/sessions/{session_id}/turns", json={"input_id": "in-1", "text": "Lucía"})
        read_turn(client, session_id, after=OPENING_EVENTS)
        stranger = TestClient(client.app)
        assert stranger.delete(f"/api/sessions/{session_id}").status_code == 401
        assert client.delete(f"/api/sessions/{session_id}").status_code == 204
        assert client.get(f"/api/sessions/{session_id}/export").status_code == 404
        assert client.get(f"/api/sessions/{session_id}/events").status_code == 404
        assert client.delete(f"/api/sessions/{session_id}").status_code == 204  # idempotent
        assert asyncio.run(store.turns.recent(SessionId(session_id), 10)) == ()


def test_the_export_of_an_open_session_carries_its_cost() -> None:
    app = build_test_app(model=FakeModel([TOOL_TURN, ANSWER_TURN]), estimate=PRICED)
    with TestClient(app) as client:
        session_id = create_session(client)
        client.post(f"/api/sessions/{session_id}/turns", json={"input_id": "a", "text": "Lucía"})
        read_turn(client, session_id, after=OPENING_EVENTS)
        document = ExportDocument.model_validate_json(
            client.get(f"/api/sessions/{session_id}/export").text
        )
        assert (document.metrics.estimated_marginal_cost_eur or 0) > 0
        assert document.metrics.cost_is_partial is False


def test_the_stored_export_of_a_closed_session_carries_its_cost() -> None:
    end = ToolCall(call_id="e1", name="end_session", arguments_json='{"reason": "not_interested"}')
    usage = ModelUsage(input_tokens=100, output_tokens=10, model_id="fake")
    model = FakeModel(
        [
            [end, usage, ModelFinished(reason="tool_calls")],
            [ModelText(text="Adiós."), usage, ModelFinished(reason="stop")],
        ]
    )
    store = MemoryStore()
    with TestClient(build_test_app(model=model, store=store, estimate=PRICED)) as client:
        session_id = create_session(client)
        client.post(f"/api/sessions/{session_id}/turns", json={"input_id": "a", "text": "no"})
        read_turn(client, session_id, after=OPENING_EVENTS)
        stored = asyncio.run(store.exports.read_snapshot(SessionId(session_id)))
        assert stored is not None
        metrics = ExportDocument.model_validate_json(stored).metrics
        assert metrics.estimated_marginal_cost_eur == pytest.approx(2 * (100 * 0.001 + 10 * 0.01))
