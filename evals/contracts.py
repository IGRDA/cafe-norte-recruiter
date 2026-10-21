"""Evaluation types and ports."""

from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, model_validator

from cafe_norte.conversation.tools import ToolName
from cafe_norte.domain.contracts import ConfigId, Sentiment, SessionState, Signal
from cafe_norte.errors import Language
from cafe_norte.observability.contracts import VersionStamp
from cafe_norte.persistence.contracts import TurnRecord
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


class Step(Frozen):
    """One model round in a scripted turn: a tool call, or the sentence that ends the turn."""

    tool: ToolName | None = None
    args: dict[str, Any] = {}
    say: str | None = None

    @model_validator(mode="after")
    def _one_of(self) -> "Step":
        if (self.tool is None) == (self.say is None):
            raise ValueError("a step is either {tool, args} or {say}")
        return self


class FakeSignal(Frozen):
    """The classifier's scripted verdict on one candidate line (``fake_signals``)."""

    sentiment: Sentiment
    evidence_text: str = ""


class Fault(Frozen):
    """Something that goes wrong on candidate line ``turn`` (1-based) of a fake run: the
    candidate speaks over Ana (``interrupt``, after ``after_sentences`` sentences were heard),
    the model provider is down for that turn (``model``), or the session store refuses its
    next save (``storage``)."""

    turn: int
    kind: Literal["interrupt", "model", "storage"]
    after_sentences: int = 1


class Scenario(Frozen):
    id: str  # S01..S18
    title: str
    config_id: ConfigId
    language: Language
    today: str = "2026-10-20"  # the fake clock's date, so relative dates in the script are fixed
    scripted_turns: tuple[str, ...]  # fake mode: the candidate's lines
    fake_script: tuple[tuple[Step, ...], ...] = ()  # one tuple of steps per candidate line
    fake_signals: tuple[FakeSignal, ...] = ()  # one per line; empty = no signal analyzer
    seconds_per_turn: float = 0.0  # fake mode: how long each turn lasts on the runtime's clock
    faults: tuple[Fault, ...] = ()  # fake mode: what goes wrong, and on which line
    persona: Persona  # live mode
    checks: tuple[Check, ...]
    rubric: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _script_matches_lines(self) -> "Scenario":
        if self.fake_script and len(self.fake_script) != len(self.scripted_turns):
            raise ValueError("fake_script needs exactly one entry per scripted turn")
        if self.fake_signals and len(self.fake_signals) != len(self.scripted_turns):
            raise ValueError("fake_signals needs exactly one entry per scripted turn")
        for fault in self.faults:
            if not 1 <= fault.turn <= len(self.scripted_turns):
                raise ValueError(f"fault on turn {fault.turn}: there is no such line")
        return self


class SessionResult(Frozen):
    """What the checks see after a fake run: the final state, the transcript, and what Ana
    said in each turn. The export document plugs in here at the export stage."""

    state: SessionState
    turns: tuple[TurnRecord, ...]
    spoken_by_turn: tuple[tuple[str, ...], ...]
    sources_by_turn: tuple[tuple[str, ...], ...] = ()  # chunk ids shown per candidate turn
    allowed_doc_ids: frozenset[str] = frozenset()  # the configuration's documents
    signals: tuple[Signal, ...] = ()  # the classifier's journaled verdicts, in order
    tools_by_turn: tuple[tuple[tuple[str, bool], ...], ...] = ()  # (tool, ok) per candidate turn
    failed_by_turn: tuple[str, ...] = ()  # the error code a turn failed with, or "" per turn

    @property
    def candidate_lines(self) -> frozenset[str]:
        return frozenset(t.text for t in self.turns if t.role == "user")


class RetrievalCase(Frozen):
    id: str
    question: str
    config_id: ConfigId
    language: Language
    kind: Literal["answerable", "unsupported", "leakage"]
    expected_sections: tuple[str, ...] = ()
    expected_facts: tuple[str, ...] = ()


class RetrievalRun(Frozen):
    """One question through the retriever: what came back, scored against the fixture."""

    case_id: str
    kind: Literal["answerable", "unsupported", "leakage"]
    returned: tuple[str, ...]  # chunk ids, best first
    fused_scores: tuple[float, ...]
    bm25_scores: tuple[float, ...] = ()
    dense_scores: tuple[float | None, ...] = ()
    hit: bool | None  # answerable: an expected section is among the returned chunks
    leaked: bool  # any returned chunk outside the configuration's documents
    milliseconds: int


class RetrievalReport(Frozen):
    kb_version: str
    embedding_model: str
    embedding_revision: str
    runs: tuple[RetrievalRun, ...]
    recall_at_3: float  # over answerable cases
    answerable: int
    leaked: int  # over every case
    unsupported_with_sources: int  # stage 1 has no floor: reported, not judged
    median_ms: int


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
    def __call__(self, result: SessionResult, check: Check) -> CheckResult: ...


class CandidateSimulator(Protocol):
    async def reply(self, persona: Persona, transcript: tuple[tuple[str, str], ...]) -> str: ...
