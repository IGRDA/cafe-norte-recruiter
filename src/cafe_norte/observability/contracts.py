"""Observability records. Everything here is metadata; free text is redacted before emit."""

from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from cafe_norte.domain.contracts import ConfigId, SessionId, StoreConfiguration, TurnId


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


class ProcessVersions(Frozen):
    """The part of a ``VersionStamp`` fixed for one process; the configuration adds the rest."""

    model_id: str
    prompt_version: str
    schema_version: str
    commit_sha: str
    stt_model: str = ""
    tts_model: str = ""
    voice_id: str = ""


def stamp(configuration: StoreConfiguration, process: ProcessVersions) -> VersionStamp:
    return VersionStamp(
        config_id=configuration.config_id,
        config_version=configuration.version,
        kb_version=configuration.kb_version,
        prompt_version=process.prompt_version,
        schema_version=process.schema_version,
        model_id=process.model_id,
        stt_model=process.stt_model,
        tts_model=process.tts_model,
        voice_id=process.voice_id,
        commit_sha=process.commit_sha,
    )


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


# A cost estimate with its price table already bound: what the export asks for.
Estimator = Callable[[SessionId, Sequence[UsageRecord]], CostEstimate]


class StructuredEvent(Frozen):
    """One JSON log line. ``payload`` never carries transcript text."""

    at: datetime
    session_id: SessionId | None
    turn_id: TurnId | None
    event: str
    payload: dict[str, Any]
