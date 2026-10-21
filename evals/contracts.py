"""Evaluation types and ports."""

from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, model_validator

from cafe_norte.conversation.tools import ToolName
from cafe_norte.domain.contracts import ConfigId, Lifecycle, Sentiment, SessionState, Signal, TurnId
from cafe_norte.errors import Language
from cafe_norte.observability.contracts import StageTiming, UsageRecord, VersionStamp
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
    withdraws_after_turn: int | None = None  # leaves politely on the next line
    declines: tuple[str, ...] = ()
    asks: tuple[str, ...] = ()  # questions to raise during the interview
    wants_interview: bool = True


class Cue(Frozen):
    """What the simulated candidate does on one line, decided by ``evals.simulator.cue``;
    the model only words it. Facts, declines and the interview wish are standing
    instructions from the persona."""

    language: Language
    mood: Literal["neutral", "frustrated"]
    ask: str | None = None  # raise this question on this line
    corrections: tuple[tuple[str, str], ...] = ()  # (field, new value) to correct now
    withdraw: bool = False  # leave the conversation politely


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
    live_checks: tuple[Check, ...] = ()  # live mode: no turn numbers; empty = not run live
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


class TurnObservation(Frozen):
    """What one candidate turn showed from the outside, folded from its runtime events: the
    fake replay and the live SSE stream build the same value (``evals/observation.py``)."""

    turn_id: TurnId = TurnId("")
    spoken: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()  # chunk ids shown
    tools: tuple[tuple[str, bool], ...] = ()  # (tool, ok)
    failed: str = ""  # the error code the turn failed with
    lifecycle: Lifecycle | None = None  # the last state the turn committed
    usage: tuple[UsageRecord, ...] = ()
    timings: tuple[StageTiming, ...] = ()
    done: bool = False  # turn_finished or turn_failed seen
    client_first_text_ms: int | None = None  # live: POST to first assistant_text, runner's clock
    client_total_ms: int | None = None  # live: POST to the turn's end, runner's clock


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


class RagasSample(Frozen):
    """One answerable retrieval question in ragas' terms (``SingleTurnSample``): what came
    back and what should have, as chunk ids."""

    case_id: str
    user_input: str
    retrieved_context_ids: tuple[str, ...]
    reference_context_ids: tuple[str, ...]


class RagasCaseScore(Frozen):
    case_id: str
    precision: float | None  # None when nothing was retrieved: ragas has no precision then
    recall: float


class RagasScores(Frozen):
    """ragas' ID-based context precision and recall, reported next to recall@3, never
    instead of it (D06)."""

    samples: int
    mean_precision: float | None  # over questions that retrieved something
    mean_recall: float
    nothing_retrieved: int
    per_case: tuple[RagasCaseScore, ...]


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
    ragas: RagasScores | None = None  # ``--ragas``: a second opinion on the answerable ones


class ComparisonCase(Frozen):
    id: str
    scenario_id: str
    emphasis: Literal[
        "correction", "rag_detour", "language_switch", "refusal", "booking", "unsupported"
    ]


class Extraction(Frozen):
    """Normalized supplied facts the record holds, out of those the persona gave (spec §13's
    ≥ 95 % target). Free text is not an exact-match fact; misses are named."""

    correct: int
    supplied: int
    misses: tuple[str, ...] = ()


class JudgeVerdict(Frozen):
    """A rubric judge's opinion: one boolean per bullet, or why there is none. A secondary
    signal next to the checks, never a pass or a fail (D06)."""

    judge_model: str
    answers: dict[str, bool] = {}  # rubric bullet -> held
    unparsable: str = ""  # why the output was not one JSON boolean per bullet
    same_model: bool  # the judge is the answering model: a known bias, labelled


class CheckResult(Frozen):
    name: str
    ok: bool
    detail: str


class RunRecord(Frozen):
    """One run of one case. Live runs fill the metrics; a run that broke before its end has
    a ``failure`` and counts as a miss, never as a skipped case."""

    case_id: str
    mode: Literal["fake", "live"]
    versions: VersionStamp | None  # None only when the session was never created
    export: ExportDocument | None
    checks: tuple[CheckResult, ...]
    judge: JudgeVerdict | None
    provider_failed: bool  # a turn failed that the case did not expect to
    estimated_cost_eur: float | None  # the answering model's, from the export
    scenario_id: str = ""
    model: str = ""  # the answering model's selector
    language: Language | None = None  # the session's starting language
    repetition: int = 1
    failure: str = ""  # why the run stopped early
    extraction: Extraction | None = None
    tool_calls: tuple[tuple[str, bool], ...] = ()  # (tool, ok), every candidate turn
    first_text_ms: tuple[int, ...] = ()  # per candidate turn that spoke, runner's clock
    turn_ms: tuple[int, ...] = ()  # per candidate turn, POST to its end, runner's clock
    lines: int = 0  # candidate lines said
    hit_turn_cap: bool = False
    cost_is_partial: bool = True

    @property
    def passed(self) -> bool:
        return not self.failure and not self.provider_failed and all(c.ok for c in self.checks)


class Report(Frozen):
    suite: Literal["scenarios", "retrieval", "comparison"]
    runs: tuple[RunRecord, ...]
    denominators: dict[str, int]


class Scorer(Protocol):
    def __call__(self, result: SessionResult, check: Check) -> CheckResult: ...


class Finished(Frozen):
    """A live session after it was ended: what the checks read, the export, and every turn as
    observed (the opening first, then one per candidate line)."""

    result: SessionResult
    export: ExportDocument
    observations: tuple[TurnObservation, ...]


class Conversation(Protocol):
    """One session seen from the candidate's side: Ana's opening, one turn per line, the end."""

    async def start(self) -> TurnObservation: ...

    async def say(self, text: str) -> TurnObservation: ...

    async def finish(self) -> Finished: ...


Speaker = Literal["ana", "candidate"]
Transcript = tuple[tuple[Speaker, str], ...]  # what was said aloud, in order


class Candidate(Protocol):
    """Who speaks for the candidate in a live run: the next line given everything said so far,
    or ``None`` when the candidate has nothing more to say."""

    async def next_line(self, transcript: Transcript) -> str | None: ...


class CandidateSimulator(Protocol):
    """Puts one cue into the candidate's words."""

    @property
    def model_id(self) -> str: ...

    async def reply(self, persona: Persona, cue: Cue, transcript: Transcript) -> str: ...
