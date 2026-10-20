"""Daily REST: private rooms and meeting tokens."""

from datetime import datetime

import httpx

from cafe_norte.domain.contracts import SessionId
from cafe_norte.voice.contracts import Room


class DailyRooms:
    def __init__(self, api_key: str, client: httpx.AsyncClient) -> None:
        raise NotImplementedError

    async def create(self, session_id: SessionId, *, expires_at: datetime) -> Room:
        raise NotImplementedError

    async def destroy(self, room: Room) -> None:
        raise NotImplementedError
