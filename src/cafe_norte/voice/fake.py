"""Fakes for the API tests: rooms that exist only in memory, a controller that records calls."""

import asyncio
from datetime import datetime

from cafe_norte.domain.contracts import SessionId
from cafe_norte.errors import Language, ServiceError
from cafe_norte.observability.contracts import StageTiming
from cafe_norte.voice.contracts import Room, VoiceStatus, VoiceTiming


class FakeRooms:
    def __init__(self) -> None:
        self.created: list[SessionId] = []
        self.destroyed: list[SessionId] = []

    async def create(self, session_id: SessionId, *, expires_at: datetime) -> Room:
        self.created.append(session_id)
        return Room(
            room_url=f"https://fake.daily.co/cn-{session_id}",
            room_name=f"cn-{session_id}",
            bot_token=f"bot-{session_id}",
            candidate_token=f"cand-{session_id}",
            expires_at=expires_at,
        )

    async def destroy(self, room: Room) -> None:
        self.destroyed.append(SessionId(room.room_name.removeprefix("cn-")))


class FakeVoiceController:
    def __init__(self) -> None:
        self.started: list[SessionId] = []
        self.stopped: list[tuple[SessionId, str]] = []
        self.observed: list[VoiceTiming] = []
        self.fail_next_start = False
        self._status: dict[SessionId, VoiceStatus] = {}
        self._ended: dict[SessionId, asyncio.Event] = {}

    async def start(self, session_id: SessionId, room: Room, language: Language) -> None:
        if self.fail_next_start:
            self.fail_next_start = False
            raise ServiceError("fake bot could not join", code="provider_unavailable")
        self.started.append(session_id)
        self._status[session_id] = "listening"
        self._ended[session_id] = asyncio.Event()

    async def stop(self, session_id: SessionId, *, reason: str) -> None:
        self.stopped.append((session_id, reason))
        self.end(session_id)

    def end(self, session_id: SessionId) -> None:
        """The pipeline finished on its own (candidate left, room expired, failure)."""
        self._status.pop(session_id, None)
        if session_id in self._ended:
            self._ended[session_id].set()

    async def wait(self, session_id: SessionId) -> None:
        event = self._ended.get(session_id)
        if event is not None:
            await event.wait()

    def status(self, session_id: SessionId) -> VoiceStatus | None:
        return self._status.get(session_id)

    def observe(self, timing: VoiceTiming) -> None:
        self.observed.append(timing)

    def timings(self, session_id: SessionId) -> tuple[StageTiming, ...]:
        return ()
