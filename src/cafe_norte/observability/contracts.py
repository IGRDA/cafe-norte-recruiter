"""Observability records. Everything here is metadata; free text is redacted before emit."""

from collections.abc import Callable, Sequence
from datetime import datetime
from types import TracebackType
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict

from cafe_norte.domain.contracts import (
    Channel,
    ConfigId,
    SessionId,
    StoreConfiguration,
    TurnId,
)
from cafe_norte.errors import Language


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


def token_usage(
    session_id: SessionId,
    turn_id: TurnId | None,
    model_id: str,
    input_tokens: float,
    output_tokens: float,
    *,
    estimated: bool,
) -> tuple[UsageRecord, UsageRecord]:
    """A model call's tokens as two records, keyed ``<model_id>:input`` and ``:output``. The
    configured model id prices them: a provider echoes a dated snapshot id instead (D36)."""
    input_record, output_record = (
        UsageRecord(
            session_id=session_id,
            turn_id=turn_id,
            kind="llm_tokens",
            quantity=quantity,
            unit_detail=f"{model_id}:{direction}",
            estimated=estimated,
        )
        for direction, quantity in (("input", input_tokens), ("output", output_tokens))
    )
    return input_record, output_record


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


Severity = Literal["INFO", "WARNING", "ERROR"]
EventName = Literal["turn_failed", "model_round", "model_round_silent", "answer_cut"]


class StructuredEvent(Frozen):
    """One JSON log line. ``payload`` never carries transcript text."""

    at: datetime
    severity: Severity
    session_id: SessionId | None
    turn_id: TurnId | None
    event: EventName
    payload: dict[str, Any]


# What a span is, in Langfuse's words: a generation is a model call, a tool a handler call, a
# retriever a knowledge lookup, an agent the round loop and a chain one round of it.
ObservationKind = Literal["span", "agent", "chain", "generation", "tool", "retriever"]
SpanValue = str | int | float | bool

# The trace of a turn is named by its root span: a stable name, never a value (D36).
ROOT_SPAN_NAME = "handle-candidate-turn"


class Span(Protocol):
    """One timed step of a turn. Parents are explicit (``child``), not ambient: a turn is an
    async generator, and a context variable does not survive its ``yield``."""

    def child(self, name: str, kind: ObservationKind = "span", **metadata: SpanValue) -> "Span": ...

    def annotate(self, **metadata: SpanValue) -> None: ...

    def set_usage(self, *, model_id: str, input_tokens: int, output_tokens: int) -> None:
        """Tokens of a generation; the adapter prices them."""
        ...

    def set_content(self, *, input: str | None = None, output: str | None = None) -> None:
        """Text of the step. A trace carries it only when the operator turned content on."""
        ...

    def first_output(self) -> None:
        """The model's first output arrived: Langfuse's time to first token."""
        ...

    def fail(self, code: str) -> None: ...

    def end(self) -> None: ...

    def __enter__(self) -> "Span": ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...


class Telemetry(Protocol):
    """Structured events and one trace per turn. The runtime holds this port; ``main`` picks
    the adapter, so a run without keys traces nothing and logs the same lines."""

    def emit(self, event: StructuredEvent) -> None: ...

    def turn(
        self,
        *,
        session_id: SessionId,
        turn_id: TurnId,
        configuration: StoreConfiguration,
        channel: Channel,
        language: Language,
    ) -> Span:
        """The root span of a turn. The adapter stamps the trace with the version stamp."""
        ...
