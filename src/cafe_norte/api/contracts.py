"""API request and response models and the event envelope."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.json_schema import JsonSchemaMode, JsonSchemaValue, models_json_schema

from cafe_norte.conversation.contracts import RuntimeEvent
from cafe_norte.domain.contracts import (
    Channel,
    ConfigId,
    InputId,
    SessionId,
    SessionState,
    TurnId,
)
from cafe_norte.errors import SWITCHABLE, ErrorCode, Language
from cafe_norte.observability.contracts import VersionStamp
from cafe_norte.persistence.contracts import TurnRecord
from cafe_norte.voice.contracts import VoiceMode, VoiceStatus

# The asynchronous classifier (D30, D52): none, a label-only model, or Jev with probabilities.
SignalsMode = Literal["off", "labels", "jev"]


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class AccessRequest(Frozen):
    code: str = Field(min_length=1, max_length=128)


class ConfigurationSummary(Frozen):
    config_id: ConfigId
    store_name: str
    city: str
    hours_per_week: int
    languages: tuple[Language, ...] = SWITCHABLE


class LanguageOption(Frozen):
    """A language Ana answers in, as the page lists it (D63)."""

    code: Language
    native: str  # the name in the language itself, for the chooser and the strip
    rtl: bool  # Arabic: the page sets dir="rtl"
    tested: bool  # Spanish and English; the rest are supported, untested


class RuntimeInfo(Frozen):
    """What the page needs before it renders: which voice to offer and the stores; and the
    commit this process runs, which the deploy waits for."""

    voice: VoiceMode
    signals: SignalsMode  # which classifier reads each message; the page says when none does
    languages: tuple[LanguageOption, ...]  # the chooser's list, in this order
    config_ids: tuple[ConfigId, ...]
    access_required: bool
    commit_sha: str


class CreateSessionRequest(Frozen):
    config_id: ConfigId
    language: Language
    channel: Channel


class CreateSessionResponse(Frozen):
    session_id: SessionId
    resume_url: str  # the private link, token in the fragment; shown once on the page
    versions: VersionStamp  # what the reviewer panel shows before the first turn


class ResumeResponse(Frozen):
    session_id: SessionId


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
    """What `GET /api/sessions/{id}` returns: one consistent read for the owner. The pending
    confirmation is ``state.pending_confirmation``; ``last_seq`` is where the stream resumes."""

    session_id: SessionId
    last_seq: int
    state: SessionState
    transcript: tuple[TurnRecord, ...]
    versions: VersionStamp


# What the page sends and what it reads. `make export-schema` writes this schema and generates
# web/src/api/contracts.ts from it (D61), so the page's types follow the API.
BROWSER_REQUESTS: tuple[type[BaseModel], ...] = (
    AccessRequest,
    CreateSessionRequest,
    ResumeRequest,
    TurnRequest,
    ConfirmationAnswer,
    VoiceTimingReport,
)
BROWSER_RESPONSES: tuple[type[BaseModel], ...] = (
    RuntimeInfo,
    LanguageOption,
    ConfigurationSummary,
    CreateSessionResponse,
    ResumeResponse,
    TurnAccepted,
    VoiceStartResponse,
    ErrorResponse,
    SessionEvent,
    SessionSnapshotResponse,
)


def browser_schema() -> JsonSchemaValue:
    """One JSON Schema whose properties name every contract the page uses. Field titles are
    dropped (a generator would name a type for each), and every field of what the page reads is
    required: the server serializes defaults too, and TypeScript narrows unions on ``type``."""
    models: list[tuple[type[BaseModel], JsonSchemaMode]] = [
        *((m, "validation") for m in BROWSER_REQUESTS),
        *((m, "serialization") for m in BROWSER_RESPONSES),
    ]
    _, schema = models_json_schema(models, ref_template="#/$defs/{model}")
    sent = {m.__name__ for m in BROWSER_REQUESTS}
    names = [m.__name__ for m in (*BROWSER_REQUESTS, *BROWSER_RESPONSES)]
    definitions = {
        name: _untitled(d, keep=True) if name in sent else _read(_untitled(d, keep=True))
        for name, d in schema["$defs"].items()
    }
    return {
        "title": "BrowserContracts",
        "type": "object",
        "properties": {name: {"$ref": f"#/$defs/{name}"} for name in names},
        "required": names,
        "additionalProperties": False,
        "$defs": definitions,
    }


def _untitled(node: object, *, keep: bool = False) -> object:
    if isinstance(node, dict):
        return {k: _untitled(v) for k, v in node.items() if keep or k != "title"}
    if isinstance(node, list):
        return [_untitled(v) for v in node]
    return node


def _read(definition: object) -> object:
    assert isinstance(definition, dict)
    if "properties" not in definition:
        return definition
    return {**definition, "required": list(definition["properties"])}
