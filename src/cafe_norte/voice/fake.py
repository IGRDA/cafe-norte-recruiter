"""Fakes for the API tests: rooms that exist only in memory, a controller that records calls."""

from datetime import datetime

from cafe_norte.domain.contracts import SessionId
from cafe_norte.errors import ServiceError
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

    async def start(self, session_id: SessionId, room: Room) -> None:
        if self.fail_next_start:
            self.fail_next_start = False
            raise ServiceError("fake bot could not join", code="provider_unavailable")
        self.started.append(session_id)
        self._status[session_id] = "listening"

    async def stop(self, session_id: SessionId, *, reason: str) -> None:
        self.stopped.append((session_id, reason))
        self._status[session_id] = "ended"

    def status(self, session_id: SessionId) -> VoiceStatus | None:
        return self._status.get(session_id)

    def observe(self, timing: VoiceTiming) -> None:
        self.observed.append(timing)

    def timings(self, session_id: SessionId) -> tuple[StageTiming, ...]:
        return ()
