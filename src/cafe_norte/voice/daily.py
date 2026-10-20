"""Daily REST: private rooms and meeting tokens. One room per session, two scoped tokens."""

from datetime import datetime, timedelta
from typing import Any

import httpx

from cafe_norte.domain.contracts import SessionId
from cafe_norte.errors import ErrorCode, ServiceError
from cafe_norte.voice.contracts import Room

API = "https://api.daily.co/v1"
ROOM_MARGIN_SECONDS = 120  # the room outlives the session cap by this much, then ejects


def room_expiry(now: datetime, *, session_seconds: float) -> datetime:
    return now + timedelta(seconds=session_seconds + ROOM_MARGIN_SECONDS)


class DailyRooms:
    """``RoomProvisioner`` on Daily. The HTTP client is the application's, bound for its
    lifespan. Failures raise ``ServiceError`` with a provider code; nothing is retried."""

    def __init__(self, api_key: str, client: httpx.AsyncClient) -> None:
        self._client = client
        self._headers = {"Authorization": f"Bearer {api_key}"}

    async def create(self, session_id: SessionId, *, expires_at: datetime) -> Room:
        name = f"cn-{session_id}"
        exp = int(expires_at.timestamp())
        room = await self._post(
            "/rooms",
            {
                "name": name,
                "privacy": "private",
                "properties": {
                    "exp": exp,
                    "eject_at_room_exp": True,
                    "enable_prejoin_ui": False,
                    "enable_chat": False,
                    "start_video_off": True,
                },
            },
        )
        bot = await self._post(
            "/meeting-tokens",
            {"properties": {"room_name": name, "is_owner": True, "exp": exp, "user_name": "Ana"}},
        )
        candidate = await self._post(
            "/meeting-tokens",
            {"properties": {"room_name": name, "exp": exp, "user_name": "Candidato"}},
        )
        return Room(
            room_url=str(room["url"]),
            room_name=name,
            bot_token=str(bot["token"]),
            candidate_token=str(candidate["token"]),
            expires_at=expires_at,
        )

    async def destroy(self, room: Room) -> None:
        """Best effort; room expiry is the fallback."""
        try:
            await self._client.delete(f"{API}/rooms/{room.room_name}", headers=self._headers)
        except httpx.HTTPError:
            pass

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await self._client.post(f"{API}{path}", json=body, headers=self._headers)
        except httpx.HTTPError as error:
            raise ServiceError(
                f"daily transport: {type(error).__name__}", code="provider_unavailable"
            ) from error
        if response.status_code != 200:
            code: ErrorCode = (
                "provider_rejected" if response.status_code < 500 else "provider_unavailable"
            )
            raise ServiceError(f"daily {path}: HTTP {response.status_code}", code=code)
        data: dict[str, Any] = response.json()
        return data
