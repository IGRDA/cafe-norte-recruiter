"""Voice types and ports. No Pipecat import here."""

from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

from cafe_norte.domain.contracts import SessionId, TurnId
from cafe_norte.observability.contracts import StageTiming


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Room(Frozen):
    """A private media room for one session: the bot and one candidate."""

    room_url: str
    room_name: str
    bot_token: str  # never leaves the server
    candidate_token: str  # short-lived, room-scoped
    expires_at: datetime


VoiceStatus = Literal["connecting", "listening", "thinking", "speaking", "paused", "ended"]


class VoiceTiming(Frozen):
    """Browser or server observation of one audible event; converted to ``StageTiming``."""

    session_id: SessionId
    turn_id: TurnId | None
    event: Literal["speech_end", "first_audio", "barge_in", "playback_stopped", "connected"]
    monotonic_ms: int
    source: Literal["browser", "server"]


class RoomProvisioner(Protocol):
    async def create(self, session_id: SessionId, *, expires_at: datetime) -> Room: ...
    async def destroy(self, room: Room) -> None:
        """Best effort; room expiry is the fallback."""
        ...


class VoiceSessionController(Protocol):
    """Starts and stops the Pipecat task for one session inside this container."""

    async def start(self, session_id: SessionId, room: Room) -> None:
        """Returns once the bot has joined; provisioning failures leave no orphan task."""
        ...

    async def stop(self, session_id: SessionId, *, reason: str) -> None: ...
    def status(self, session_id: SessionId) -> VoiceStatus | None: ...
    def timings(self, session_id: SessionId) -> tuple[StageTiming, ...]: ...
