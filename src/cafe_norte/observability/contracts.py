"""Observability records. Everything here is metadata; free text is redacted before emit."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from cafe_norte.domain.contracts import ConfigId, SessionId, TurnId


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class VersionStamp(Frozen):
    """Attached to every session and evaluation run."""

    config_id: ConfigId
    config_version: str
    kb_version: str
    prompt_version: str
    schema_version: str
    model_id: str
    stt_model: str = ""
    tts_model: str = ""
    voice_id: str = ""
    commit_sha: str


Stage = Literal[
    "speech_end_to_transcript",
    "llm_first_output",
    "llm_total",
    "tool",
    "tts_first_audio",
    "useful_answer",  # end of user speech to first audible non-filler answer
    "barge_in_to_stop",
    "text_first_token",
    "text_total",
]


class StageTiming(Frozen):
    session_id: SessionId
    turn_id: TurnId
    stage: Stage
    milliseconds: int
    source: Literal["server", "browser", "server_proxy"]  # never subtract across clocks
    tool_name: str = ""


UsageKind = Literal["llm_tokens", "tts_characters", "stt_seconds", "media_participant_minutes"]


class UsageRecord(Frozen):
    session_id: SessionId
    turn_id: TurnId | None
    kind: UsageKind
    quantity: float
    unit_detail: str  # e.g. "input" / "output" for tokens, model or voice id
    estimated: bool  # true when inferred (cancelled generation, missing provider report)


class Price(Frozen):
    kind: UsageKind
    unit_detail: str
    eur_per_unit: float


class PriceTable(Frozen):
    version: str
    currency: Literal["EUR"] = "EUR"
    verified_on: datetime
    prices: tuple[Price, ...]


class CostEstimate(Frozen):
    session_id: SessionId
    marginal_eur: float
    missing_prices: tuple[str, ...]  # usage kinds with no price: the total is partial
    price_table_version: str


class StructuredEvent(Frozen):
    """One JSON log line. ``payload`` never carries transcript text."""

    at: datetime
    session_id: SessionId | None
    turn_id: TurnId | None
    event: str
    payload: dict[str, Any]
