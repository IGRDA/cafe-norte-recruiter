"""Evaluation types and ports."""

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

from cafe_norte.domain.contracts import ConfigId
from cafe_norte.errors import Language
from cafe_norte.observability.contracts import VersionStamp
from cafe_norte.persistence.export import ExportDocument


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Persona(Frozen):
    """Facts the simulated candidate knows and how they behave."""

    facts: dict[str, str]
    corrections: tuple[tuple[str, str], ...] = ()  # (field, new value) applied mid-conversation
    mood: Literal["neutral", "frustrated"] = "neutral"
    switch_language_after_turn: int | None = None
    declines: tuple[str, ...] = ()
    asks: tuple[str, ...] = ()  # questions to raise during the interview
    wants_interview: bool = True


class Check(Frozen):
    name: str
    args: dict[str, str] = {}


class Scenario(Frozen):
    id: str  # S01..S18
    title: str
    config_id: ConfigId
    language: Language
    scripted_turns: tuple[str, ...]  # fake mode
    persona: Persona  # live mode
    checks: tuple[Check, ...]
    rubric: tuple[str, ...] = ()


class RetrievalCase(Frozen):
    id: str
    question: str
    config_id: ConfigId
    language: Language
    kind: Literal["answerable", "unsupported", "leakage"]
    expected_sections: tuple[str, ...] = ()
    expected_facts: tuple[str, ...] = ()


class ComparisonCase(Frozen):
    id: str
    scenario_id: str
    emphasis: Literal[
        "correction", "rag_detour", "language_switch", "refusal", "booking", "unsupported"
    ]


class CheckResult(Frozen):
    name: str
    ok: bool
    detail: str


class RunRecord(Frozen):
    case_id: str
    mode: Literal["fake", "live"]
    versions: VersionStamp
    export: ExportDocument | None
    checks: tuple[CheckResult, ...]
    judge: dict[str, bool] | None
    provider_failed: bool
    latency_ms: dict[str, int]
    estimated_cost_eur: float | None


class Report(Frozen):
    suite: Literal["scenarios", "retrieval", "comparison"]
    runs: tuple[RunRecord, ...]
    denominators: dict[str, int]


class Scorer(Protocol):
    def __call__(self, export: ExportDocument, check: Check) -> CheckResult: ...


class CandidateSimulator(Protocol):
    async def reply(self, persona: Persona, transcript: tuple[tuple[str, str], ...]) -> str: ...
