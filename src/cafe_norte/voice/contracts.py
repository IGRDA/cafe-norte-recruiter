"""Voice types and ports. No Pipecat import here."""

from datetime import datetime, timedelta
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

from cafe_norte.domain.contracts import SessionId, TurnId
from cafe_norte.errors import Language
from cafe_norte.observability.contracts import StageTiming


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


ROOM_MARGIN_SECONDS = 120  # a room outlives the session cap by this much, then ejects


def room_expiry(now: datetime, *, session_seconds: float) -> datetime:
    return now + timedelta(seconds=session_seconds + ROOM_MARGIN_SECONDS)


class Room(Frozen):
    """A private media room for one session: the bot and one candidate."""

    room_url: str
    room_name: str
    bot_token: str  # never leaves the server
    candidate_token: str  # short-lived, room-scoped
    expires_at: datetime


VoiceStatus = Literal["connecting", "listening", "thinking", "speaking", "paused", "ended"]
# The hosted pipeline's providers, named once: the pipeline runs them and the version stamp and
# the price table (observability/prices) refer to them by these ids.
STT_MODEL = "nova-3"
TTS_MODEL = "eleven_flash_v2_5"

VoiceMode = Literal["off", "pipecat"]  # the browser's own speech was removed (D45)


class VoiceTexts(Frozen):
    """The fixed sentences voice needs. They live in ``conversation/prompts`` and are handed
    in by the composition root, because this package may not import prompts."""

    opening: str
    filler: str  # spoken only while a tool is running longer than the filler delay
    idle_prompt: str  # after the first silence window
    failure: str  # after a turn failed, so the candidate is never left in silence


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

    async def start(self, session_id: SessionId, room: Room, language: Language) -> None:
        """Returns once the bot has joined; provisioning failures leave no orphan task. Ana
        opens in ``language``."""
        ...

    async def stop(self, session_id: SessionId, *, reason: str) -> None: ...

    async def wait(self, session_id: SessionId) -> None:
        """Returns once the voice session has ended for any reason (stop, candidate left,
        room expiry, failure); returns at once for an unknown session."""
        ...

    def status(self, session_id: SessionId) -> VoiceStatus | None: ...
    def observe(self, timing: VoiceTiming) -> None:
        """A browser- or server-observed audible event; paired into ``StageTiming`` later."""
        ...

    def timings(self, session_id: SessionId) -> tuple[StageTiming, ...]: ...
