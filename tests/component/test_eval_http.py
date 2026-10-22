"""The live runner's HTTP adapter against a scripted server: no socket, no provider. The frames
come from the app's own SSE encoder, so a change in the wire format breaks here first."""

import json
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime

import httpx
import pytest
from evals.live import HttpConversation, LiveError

from cafe_norte.api.contracts import SessionEvent, SessionSnapshotResponse
from cafe_norte.api.events import encode
from cafe_norte.conversation.contracts import (
    AssistantText,
    RuntimeEvent,
    SourcesShown,
    ToolFinished,
    TurnFailed,
    TurnFinished,
    TurnStarted,
)
from cafe_norte.domain.contracts import ConfigId, SessionId, SessionState, TurnId
from tests.support.evals import EXPORT

SID = SessionId("sess-1")
AT = datetime(2026, 10, 21, 10, 0, tzinfo=UTC)


def turn(n: int, *events: RuntimeEvent, end: bool = True) -> list[RuntimeEvent]:
    tid = TurnId(f"t{n}")
    closing: list[RuntimeEvent] = (
        [TurnFinished(turn_id=tid, interrupted=False, usage=(), timings=())] if end else []
    )
    return [TurnStarted(turn_id=tid, language="es", text=""), *events, *closing]


OPENING = turn(0, AssistantText(text="Hola, soy Ana.", spoken_form="Hola, soy Ana."))
ANSWER = turn(
    1,
    ToolFinished(name="search_knowledge", ok=True, summary=""),
    SourcesShown(question="q", chunk_ids=("offer#horas",), titles=(), sections=(), excerpts=()),
    AssistantText(text="Son 30 horas.", spoken_form="Son 30 horas."),
)


class ScriptedServer:
    """Answers the endpoints the runner uses. Each POSTed turn appends its scripted events;
    the events stream replays everything after ``Last-Event-ID`` and then closes, which the
    real server never does, so the adapter's reconnect path runs on every turn."""

    def __init__(self, turns: Sequence[list[RuntimeEvent]], *, access_code: str = "") -> None:
        self.turns = list(turns)
        self.access_code = access_code
        self.events: list[SessionEvent] = []
        self.posted: list[dict[str, object]] = []
        self.ended = False

    def _append(self, payloads: list[RuntimeEvent]) -> None:
        for payload in payloads:
            seq = len(self.events) + 1
            self.events.append(
                SessionEvent(session_id=SID, seq=seq, turn_id=None, at=AT, payload=payload)
            )

    async def handle(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        if request.content and request.headers.get("content-type") != "application/json":
            return httpx.Response(422)  # FastAPI parses a body only when it is declared JSON
        if path == "/api/access":
            ok = json.loads(request.content)["code"] == self.access_code
            return httpx.Response(204 if ok else 401, json=None if ok else {"code": "x"})
        if path == "/api/sessions" and method == "POST":
            self._append(self.turns.pop(0))
            return httpx.Response(
                201,
                json={
                    "session_id": SID,
                    "resume_url": "/#resume=x",
                    "versions": EXPORT.versions.model_dump(),
                },
            )
        if path == f"/api/sessions/{SID}/turns":
            self.posted.append(json.loads(request.content))
            if self.turns:
                self._append(self.turns.pop(0))
            return httpx.Response(202, json={"input_id": self.posted[-1]["input_id"]})
        if path == f"/api/sessions/{SID}/events":
            after = int(request.headers.get("Last-Event-ID", "0"))
            body = b"".join(encode(e) for e in self.events if e.seq > after)
            return httpx.Response(
                200, headers={"content-type": "text/event-stream"}, stream=_bytes(body)
            )
        if path == f"/api/sessions/{SID}/end":
            self.ended = True
            return httpx.Response(204)
        if path == f"/api/sessions/{SID}/export":
            return httpx.Response(200, content=EXPORT.model_dump_json())
        if path == f"/api/sessions/{SID}":
            state = SessionState(
                session_id=SID,
                config_id=ConfigId("chamberi_barista_v1"),
                config_version="1",
                language="es",
                channel="text",
                created_at=AT,
                lifecycle="completed",
            )
            snapshot = SessionSnapshotResponse(
                session_id=SID,
                last_seq=len(self.events),
                state=state,
                transcript=EXPORT.transcript,
                versions=EXPORT.versions,
            )
            return httpx.Response(200, content=snapshot.model_dump_json())
        return httpx.Response(404)


class _bytes(httpx.AsyncByteStream):
    def __init__(self, body: bytes) -> None:
        self.body = body

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for line in self.body.splitlines(keepends=True):  # frame boundaries mid-chunk
            yield line


def conversation(server: ScriptedServer, **kwargs: object) -> HttpConversation:
    client = httpx.AsyncClient(transport=httpx.MockTransport(server.handle), base_url="http://test")
    return HttpConversation(
        client,
        config_id=ConfigId("chamberi_barista_v1"),
        language="es",
        allowed_doc_ids=frozenset({"offer"}),
        **kwargs,  # type: ignore[arg-type]
    )


async def test_the_opening_and_each_turn_are_read_until_the_turn_ends() -> None:
    server = ScriptedServer([OPENING, ANSWER])
    live = conversation(server)
    opening = await live.start()
    assert opening.spoken == ("Hola, soy Ana.",)
    answer = await live.say("¿Cuántas horas son?")
    assert answer.spoken == ("Son 30 horas.",)
    assert answer.sources == ("offer#horas",)
    assert answer.tools == (("search_knowledge", True),)
    assert answer.done
    assert answer.client_first_text_ms is not None
    assert answer.client_total_ms is not None
    assert server.posted[0]["text"] == "¿Cuántas horas son?"


async def test_every_turn_gets_its_own_input_id() -> None:
    server = ScriptedServer([OPENING, turn(1), turn(2)])
    live = conversation(server)
    await live.start()
    await live.say("uno")
    await live.say("dos")
    assert len({p["input_id"] for p in server.posted}) == 2


async def test_a_failed_turn_returns_its_code() -> None:
    failed: list[RuntimeEvent] = [
        TurnFailed(turn_id=TurnId("t1"), code="provider_unavailable", message="m")
    ]
    live = conversation(ScriptedServer([OPENING, failed]))
    await live.start()
    observation = await live.say("hola")
    assert observation.failed == "provider_unavailable"


async def test_a_turn_that_never_ends_is_reported_not_awaited_forever() -> None:
    live = conversation(ScriptedServer([OPENING, turn(1, end=False)]), turn_timeout=0.2)
    await live.start()
    observation = await live.say("hola")
    assert observation.failed == "no_turn_end"
    assert not observation.done


async def test_a_wrong_access_code_stops_before_a_session_exists() -> None:
    server = ScriptedServer([OPENING], access_code="right")
    with pytest.raises(LiveError, match="access"):
        await conversation(server, access_code="wrong").start()
    assert not server.events


async def test_finish_ends_the_session_and_scores_the_candidate_lines_only() -> None:
    server = ScriptedServer([OPENING, ANSWER])
    live = conversation(server)
    await live.start()
    await live.say("¿Cuántas horas son?")
    finished = await live.finish()
    assert server.ended
    assert finished.export == EXPORT
    assert finished.result.spoken_by_turn == (("Son 30 horas.",),)
    assert finished.result.allowed_doc_ids == frozenset({"offer"})
    assert finished.observations[0].spoken == ("Hola, soy Ana.",)
