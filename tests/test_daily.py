"""Daily REST: a private room per session and two short-lived tokens, against a scripted
transport. The real API is touched only by the manual voice smoke."""

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from cafe_norte.domain.contracts import SessionId
from cafe_norte.errors import ServiceError
from cafe_norte.voice.daily import DailyRooms

EXPIRES = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


def transport(status: int = 200) -> tuple[httpx.MockTransport, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if status != 200:
            return httpx.Response(status, json={"error": "nope"})
        if request.url.path == "/v1/rooms" and request.method == "POST":
            name = json.loads(request.content)["name"]
            return httpx.Response(
                200, json={"name": name, "url": f"https://cafe-norte.daily.co/{name}"}
            )
        if request.url.path == "/v1/meeting-tokens":
            owner = json.loads(request.content)["properties"].get("is_owner", False)
            return httpx.Response(200, json={"token": "bot-token" if owner else "candidate-token"})
        if request.method == "DELETE":
            return httpx.Response(200, json={"deleted": True})
        return httpx.Response(404)

    return httpx.MockTransport(handler), seen


async def test_create_makes_a_private_expiring_room_and_two_scoped_tokens() -> None:
    mock, seen = transport()
    async with httpx.AsyncClient(transport=mock) as client:
        rooms = DailyRooms("k", client)
        room = await rooms.create(SessionId("abc123"), expires_at=EXPIRES)
    assert room.room_url == "https://cafe-norte.daily.co/cn-abc123"
    assert room.room_name == "cn-abc123"
    assert (room.bot_token, room.candidate_token) == ("bot-token", "candidate-token")
    assert room.expires_at == EXPIRES

    create = json.loads(seen[0].content)
    assert create["privacy"] == "private"
    assert create["properties"]["exp"] == int(EXPIRES.timestamp())
    assert create["properties"]["eject_at_room_exp"] is True
    assert create["properties"]["enable_prejoin_ui"] is False
    assert seen[0].headers["authorization"] == "Bearer k"
    tokens = [json.loads(r.content)["properties"] for r in seen[1:3]]
    assert [t["room_name"] for t in tokens] == ["cn-abc123", "cn-abc123"]
    assert [t.get("is_owner", False) for t in tokens] == [True, False]
    assert all(t["exp"] == int(EXPIRES.timestamp()) for t in tokens)


async def test_a_provider_failure_is_a_coded_error_and_leaves_no_half_room() -> None:
    mock, seen = transport(status=401)
    async with httpx.AsyncClient(transport=mock) as client:
        with pytest.raises(ServiceError) as raised:
            await DailyRooms("k", client).create(SessionId("abc"), expires_at=EXPIRES)
    assert raised.value.code == "provider_rejected"
    assert len(seen) == 1


async def test_destroy_is_best_effort() -> None:
    mock, seen = transport()
    async with httpx.AsyncClient(transport=mock) as client:
        rooms = DailyRooms("k", client)
        room = await rooms.create(SessionId("abc"), expires_at=EXPIRES)
        await rooms.destroy(room)
        assert seen[-1].method == "DELETE" and seen[-1].url.path == "/v1/rooms/cn-abc"
    failing, _ = transport(status=500)
    async with httpx.AsyncClient(transport=failing) as client:
        await DailyRooms("k", client).destroy(room)  # swallowed: expiry is the fallback


def test_room_expiry_is_the_session_cap_plus_a_margin() -> None:
    from cafe_norte.voice.daily import room_expiry

    now = datetime(2026, 10, 20, 10, 0, tzinfo=UTC)
    assert room_expiry(now, session_seconds=480) == now + timedelta(seconds=480 + 120)
