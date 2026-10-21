"""API request and response models and the event envelope."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from cafe_norte.conversation.contracts import RuntimeEvent
from cafe_norte.domain.contracts import Channel, ConfigId, InputId, SessionId, TurnId
from cafe_norte.errors import ErrorCode, Language
from cafe_norte.voice.contracts import VoiceMode, VoiceStatus


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class AccessRequest(Frozen):
    code: str = Field(min_length=1, max_length=128)


class ConfigurationSummary(Frozen):
    config_id: ConfigId
    store_name: str
    city: str
    hours_per_week: int
    languages: tuple[Language, ...] = ("es", "en")


class RuntimeInfo(Frozen):
    """What the page needs before it renders: which voice to offer and the stores."""

    voice: VoiceMode
    config_ids: tuple[ConfigId, ...]
    access_required: bool


class CreateSessionRequest(Frozen):
    config_id: ConfigId
    language: Language
    channel: Channel


class CreateSessionResponse(Frozen):
    session_id: SessionId
    resume_url: str | None  # token in the fragment; shown once; None until resume links ship


class TurnRequest(Frozen):
    input_id: InputId
    text: str = Field(min_length=1, max_length=2000)
    expected_revision: int | None = None


class TurnAccepted(Frozen):
    """The turn is queued; its events arrive on the session stream."""

    input_id: InputId


class ConfirmationAnswer(Frozen):
    input_id: InputId
    answer: Literal["affirm", "deny"]
    expected_revision: int


class VoiceStartResponse(Frozen):
    room_url: str
    candidate_token: str
    expires_at: datetime


class VoiceTimingReport(Frozen):
    turn_id: TurnId | None
    event: Literal["speech_end", "first_audio", "barge_in", "playback_stopped", "connected"]
    monotonic_ms: int


class ResumeRequest(Frozen):
    token: str = Field(min_length=32, max_length=256)


class ErrorResponse(Frozen):
    code: ErrorCode
    message: str


class VoiceState(Frozen):
    type: Literal["voice_state"] = "voice_state"
    status: VoiceStatus


class SessionEvent(Frozen):
    """SSE envelope. ``seq`` is monotonic per session and doubles as the SSE id."""

    session_id: SessionId
    seq: int
    turn_id: TurnId | None
    at: datetime
    payload: RuntimeEvent | VoiceState


class SessionSnapshotResponse(Frozen):
    """What `GET /api/sessions/{id}` returns; shape finalized with the routes."""

    session_id: SessionId
    last_seq: int
    state: dict[str, Any]
    transcript: tuple[dict[str, Any], ...]
