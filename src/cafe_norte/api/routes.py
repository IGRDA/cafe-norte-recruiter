"""Routes from ports."""

import asyncio
import uuid
from collections.abc import Coroutine
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import StreamingResponse

from cafe_norte.api import events as sse
from cafe_norte.api.access import ACCESS_COOKIE, SESSION_COOKIE, AccessGate
from cafe_norte.api.contracts import (
    AccessRequest,
    ConfigurationSummary,
    CreateSessionRequest,
    CreateSessionResponse,
    RuntimeInfo,
    TurnAccepted,
    TurnRequest,
    VoiceStartResponse,
    VoiceTimingReport,
)
from cafe_norte.conversation.contracts import ConversationRuntime, TurnInput
from cafe_norte.domain.contracts import ConfigId, SessionId, SessionState, StoreConfiguration
from cafe_norte.errors import ServiceError
from cafe_norte.persistence.contracts import Store
from cafe_norte.voice.contracts import (
    Room,
    RoomProvisioner,
    VoiceMode,
    VoiceSessionController,
    VoiceTiming,
    room_expiry,
)

VOICE_RESERVE_EUR = 0.5  # per-session spend reservation until pricing lands


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
    voice_mode: VoiceMode = "off",
    max_voice_sessions: int = 2,
    session_seconds: float = 480.0,
) -> APIRouter:
    """Voice endpoints return ``provider_unavailable`` when ``rooms``/``voice`` are None."""
    router = APIRouter()
    hosted_voice = voice_mode == "pipecat" and rooms is not None and voice is not None

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

    @router.get("/api/runtime")
    async def runtime_info() -> RuntimeInfo:
        return RuntimeInfo(
            voice=voice_mode,
            config_ids=tuple(configurations),
            access_required=gate.requires_code,
        )

    @router.post("/api/access", status_code=status.HTTP_204_NO_CONTENT)
    async def access(body: AccessRequest, response: Response) -> Response:
        """The shared demo code opens session creation for this browser."""
        if not gate.check_code(body.code):
            raise ServiceError("wrong access code", code="unauthorized")
        response = Response(status_code=status.HTTP_204_NO_CONTENT)
        response.set_cookie(
            ACCESS_COOKIE,
            gate.issue_access_cookie(),
            httponly=True,
            samesite="lax",
            path="/api",
        )
        return response

    @router.post("/api/sessions/{session_id}/voice")
    async def start_voice(session_id: str, request: Request) -> VoiceStartResponse:
        """Admission, a private room, the bot joins. A failure at any step leaves nothing
        behind: the slot is released and the room destroyed."""
        sid = owner(request, session_id)
        if not hosted_voice or rooms is None or voice is None:
            raise ServiceError("voice is not configured", code="provider_unavailable")
        if await store.sessions.get(sid) is None:
            raise ServiceError("no such session", code="not_found")
        if voice.status(sid) is not None:
            raise ServiceError("voice already running for this session", code="conflict")
        if not await store.admission.acquire(
            sid, max_active=max_voice_sessions, reserve_eur=VOICE_RESERVE_EUR
        ):
            raise ServiceError("voice capacity reached", code="busy")
        expires_at = room_expiry(datetime.now(UTC), session_seconds=session_seconds)
        try:
            room = await rooms.create(sid, expires_at=expires_at)
        except Exception:
            await store.admission.release(sid, actual_eur=0.0)
            raise
        try:
            await voice.start(sid, room)
        except Exception:
            await rooms.destroy(room)
            await store.admission.release(sid, actual_eur=0.0)
            raise
        tasks.start(_release_when_over(voice, rooms, store, sid, room))
        return VoiceStartResponse(
            room_url=room.room_url, candidate_token=room.candidate_token, expires_at=expires_at
        )

    @router.post("/api/sessions/{session_id}/voice/timings", status_code=status.HTTP_204_NO_CONTENT)
    async def voice_timings(session_id: str, body: VoiceTimingReport, request: Request) -> Response:
        sid = owner(request, session_id)
        if voice is not None:
            voice.observe(
                VoiceTiming(
                    session_id=sid,
                    turn_id=body.turn_id,
                    event=body.event,
                    monotonic_ms=body.monotonic_ms,
                    source="browser",
                )
            )
        return Response(status_code=status.HTTP_204_NO_CONTENT)

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
        body: CreateSessionRequest, request: Request, response: Response
    ) -> CreateSessionResponse:
        if not gate.access_cookie_valid(request.cookies.get(ACCESS_COOKIE)):
            raise ServiceError("access code required", code="unauthorized")
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
            created_at=datetime.now(UTC),
        )
        await store.sessions.create(state, access_hash="")
        tasks.start(_drain(runtime.open_session(session_id)))
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


async def _release_when_over(
    voice: VoiceSessionController,
    rooms: RoomProvisioner,
    store: Store,
    session_id: SessionId,
    room: Room,
) -> None:
    """However the voice session ends (stop, candidate left, expiry, failure), the slot and
    the room go with it; otherwise capacity leaks until the next deploy."""
    await voice.wait(session_id)
    await rooms.destroy(room)
    await store.admission.release(session_id, actual_eur=0.0)


async def _drain(events: Any) -> None:
    async for _ in events:
        pass


def _last_event_id(header: str | None) -> int:
    try:
        return max(int(header or 0), 0)
    except ValueError:
        return 0
