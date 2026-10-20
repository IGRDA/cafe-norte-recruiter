"""Routes from ports."""

import asyncio
import uuid
from collections.abc import Coroutine
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import StreamingResponse

from cafe_norte.api import events as sse
from cafe_norte.api.access import SESSION_COOKIE, AccessGate
from cafe_norte.api.contracts import (
    ConfigurationSummary,
    CreateSessionRequest,
    CreateSessionResponse,
    TurnAccepted,
    TurnRequest,
)
from cafe_norte.conversation.contracts import ConversationRuntime, TurnInput
from cafe_norte.domain.contracts import ConfigId, SessionId, SessionState, StoreConfiguration
from cafe_norte.errors import ServiceError
from cafe_norte.persistence.contracts import Store
from cafe_norte.voice.contracts import RoomProvisioner, VoiceSessionController


class TurnTasks:
    """Background turn execution. Each task drains ``run_turn``; the runtime journals events,
    the SSE stream reads them. Strong references keep tasks alive until they finish."""

    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[None]] = set()

    def start(self, work: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(work)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def shutdown(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)


def build_router(
    *,
    runtime: ConversationRuntime,
    store: Store,
    configurations: dict[ConfigId, StoreConfiguration],
    rooms: RoomProvisioner | None,
    voice: VoiceSessionController | None,
    gate: AccessGate,
    tasks: TurnTasks,
) -> APIRouter:
    """Voice endpoints return ``provider_unavailable`` when ``rooms``/``voice`` are None."""
    router = APIRouter()

    def owner(request: Request, session_id: str) -> SessionId:
        found = gate.session_from_cookie(request.cookies.get(SESSION_COOKIE))
        if found is None or found != session_id:
            raise ServiceError("not the session owner", code="unauthorized")
        return found

    @router.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/health/ready")
    async def ready() -> dict[str, str]:
        if not await store.check_ready():
            raise ServiceError("store not ready", code="provider_unavailable")
        return {"status": "ok"}

    @router.get("/api/configurations")
    async def list_configurations() -> list[ConfigurationSummary]:
        return [
            ConfigurationSummary(
                config_id=c.config_id,
                store_name=c.store_name,
                city=c.city,
                hours_per_week=c.hours_per_week,
            )
            for c in configurations.values()
        ]

    @router.post("/api/sessions", status_code=status.HTTP_201_CREATED)
    async def create_session(
        body: CreateSessionRequest, response: Response
    ) -> CreateSessionResponse:
        configuration = configurations.get(body.config_id)
        if configuration is None:
            raise ServiceError("unknown configuration", code="not_found")
        session_id = SessionId(uuid.uuid4().hex)
        state = SessionState(
            session_id=session_id,
            config_id=configuration.config_id,
            config_version=configuration.version,
            language=body.language,
            channel=body.channel,
        )
        await store.sessions.create(state, access_hash="")
        response.set_cookie(
            SESSION_COOKIE,
            gate.issue_session_cookie(session_id),
            httponly=True,
            samesite="lax",
            path="/api/sessions",
        )
        return CreateSessionResponse(session_id=session_id, resume_url=None)

    @router.post("/api/sessions/{session_id}/turns", status_code=status.HTTP_202_ACCEPTED)
    async def post_turn(session_id: str, body: TurnRequest, request: Request) -> TurnAccepted:
        sid = owner(request, session_id)
        state = await store.sessions.get(sid)
        if state is None:
            raise ServiceError("no such session", code="not_found")
        turn = TurnInput(
            session_id=sid,
            input_id=body.input_id,
            text=body.text,
            channel=state.channel,
            received_at=datetime.now(UTC),
            expected_revision=body.expected_revision,
        )
        tasks.start(_drain(runtime.run_turn(turn)))
        return TurnAccepted(input_id=body.input_id)

    @router.get("/api/sessions/{session_id}/events")
    async def session_events(session_id: str, request: Request) -> StreamingResponse:
        sid = owner(request, session_id)
        if await store.sessions.get(sid) is None:
            raise ServiceError("no such session", code="not_found")
        after = _last_event_id(request.headers.get("last-event-id"))
        return StreamingResponse(
            sse.stream(store.events, sid, after_seq=after),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return router


async def _drain(events: Any) -> None:
    async for _ in events:
        pass


def _last_event_id(header: str | None) -> int:
    try:
        return max(int(header or 0), 0)
    except ValueError:
        return 0
