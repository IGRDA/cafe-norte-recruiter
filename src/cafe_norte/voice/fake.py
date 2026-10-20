"""Fakes for the API tests: rooms that exist only in memory, a controller that records calls."""

from datetime import datetime

from cafe_norte.domain.contracts import SessionId
from cafe_norte.observability.contracts import StageTiming
from cafe_norte.voice.contracts import Room, VoiceStatus


class FakeRooms:
    async def create(self, session_id: SessionId, *, expires_at: datetime) -> Room:
        raise NotImplementedError

    async def destroy(self, room: Room) -> None:
        raise NotImplementedError


class FakeVoiceController:
    async def start(self, session_id: SessionId, room: Room) -> None:
        raise NotImplementedError

    async def stop(self, session_id: SessionId, *, reason: str) -> None:
        raise NotImplementedError

    def status(self, session_id: SessionId) -> VoiceStatus | None:
        raise NotImplementedError

    def timings(self, session_id: SessionId) -> tuple[StageTiming, ...]:
        raise NotImplementedError
