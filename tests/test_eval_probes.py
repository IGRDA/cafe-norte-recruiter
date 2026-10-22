"""QA probes (D51): one question, one session, the answer and its sources recorded; the
deterministic reads over it; ragas' ToolCallF1 offline; the judges behind their port."""

from pathlib import Path

import httpx
import pytest
from evals import scorecard_live
from evals.contracts import AnswerJudge, Exchange, ProbeRecord, RetrievalCase, RunRecord, Step
from evals.live import HttpConversation, serve
from evals.probes import probe
from evals.ragas_bridge import (
    FakeAnswerJudge,
    RagasJudge,
    judge_from,
    judge_probes,
    judge_runs,
    tool_call_f1,
)
from evals.retrieval import load_cases
from evals.runner import load_scenarios, run_fake, script_events
from evals.scorecard import scorecard
from evals.scorers import abstained, exchanges, facts_missing
from evals.testset import kb_chunks

from cafe_norte.domain.contracts import ConfigId
from cafe_norte.knowledge.contracts import RetrievedChunk
from cafe_norte.knowledge.fake import FakeRetriever
from cafe_norte.model.fake import FakeModel
from tests.support import build_test_app

SALARY = next(c for c in kb_chunks() if c.chunk_id == "offer_chamberi#salario")
QUESTION = "¿Cuánto se cobra?"


def case(kind: str = "answerable") -> RetrievalCase:
    return RetrievalCase.model_validate(
        {
            "id": "R02",
            "question": QUESTION,
            "config_id": "chamberi_barista_v1",
            "language": "es",
            "kind": kind,
            **(
                {
                    "expected_sections": ["offer_chamberi#salario"],
                    "expected_facts": ["1.380", "14 pagas"],
                    "reference": "Son 1.380 euros brutos al mes en 14 pagas.",
                }
                if kind == "answerable"
                else {}
            ),
        }
    )


async def asked(answer: str) -> ProbeRecord:
    """One probe over loopback: the model searches once, then says ``answer``."""
    steps = (
        Step(tool="search_knowledge", args={"question": QUESTION, "queries": ["salario"]}),
        Step(say=answer),
    )
    retriever = FakeRetriever(
        {"salario": (RetrievedChunk(chunk=SALARY, fused_score=0.03, bm25_rank=1, dense_rank=1),)}
    )
    app = build_test_app(model=FakeModel(script_events(steps)), retriever=retriever)
    async with serve(app) as base_url, httpx.AsyncClient(base_url=base_url) as client:
        conversation = HttpConversation(
            client,
            config_id=ConfigId("chamberi_barista_v1"),
            language="es",
            allowed_doc_ids=frozenset({"faq"}),  # the store's documents aside, for the test
        )
        return await probe(
            case(),
            conversation,
            model="fake",
            chunk_text={SALARY.chunk_id: SALARY.text},
            allowed_doc_ids=frozenset({"faq"}),
        )


async def test_a_probe_records_the_answer_its_sources_and_the_tools_it_called() -> None:
    record = await asked("Según la oferta, son 1.380 euros brutos al mes en 14 pagas.")
    assert record.answer.startswith("Según la oferta, son 1.380 euros")
    assert record.sources == ("offer_chamberi#salario",)
    assert record.contexts == (SALARY.text,)
    assert record.tools == ("search_knowledge",)
    assert record.foreign_sources == ("offer_chamberi#salario",)  # the test allowed only faq
    assert record.run.export is not None and not record.run.failure
    assert record.expected_facts == ("1.380", "14 pagas")

    card = scorecard([], {}, probes=[record])
    rows = {m.spec.id: m for m in card.metrics}
    assert (rows["fact_presence"].k, rows["fact_presence"].n) == (2, 2)
    assert rows["cross_store_free"].ok is False
    assert rows["completed"].n == 1


def test_facts_ignore_case_accents_separators_and_accept_alternatives() -> None:
    answer = "It's 1,380 euros a month, paid on the LAST WORKING DAY; café included."
    assert facts_missing(answer, ["1.380", "último día laborable|last working day"]) == []
    assert facts_missing(answer, ["14 pagas|14 payments", "cafe"]) == ["14 pagas|14 payments"]


@pytest.mark.parametrize(
    ("answer", "tools", "held"),
    [
        ("Eso no lo sé, pero puedo pedir que alguien del equipo te lo cuente.", (), True),
        ("I don't have that information, sorry.", (), True),
        ("That's not something I know, but I can ask for you.", (), True),
        ("Hay parking gratuito para el equipo.", (), False),
        ("Lo anoto para que te respondan.", ("request_human_followup",), True),
    ],
)
def test_an_unsupported_question_abstains_by_saying_so_or_asking_a_person(
    answer: str, tools: tuple[str, ...], held: bool
) -> None:
    assert abstained(answer, tools) is held


async def test_tool_call_f1_scores_tool_names_with_ragas_offline() -> None:
    assert await tool_call_f1("q", "a", ["search_knowledge"]) == 1.0
    assert await tool_call_f1("q", "a", ["search_knowledge", "search_knowledge"]) == 1.0
    assert round(await tool_call_f1("q", "a", ["search_knowledge", "end_session"]), 2) == 0.67
    assert await tool_call_f1("q", "a", []) == 0.0


async def test_probes_get_tool_f1_always_and_judge_scores_only_with_a_judge() -> None:
    record = await asked("Son 1.380 euros brutos al mes en 14 pagas.")
    (free,) = await judge_probes([record], [case()], None)
    assert free.scores == {"probe_tool_f1": 1.0}
    (judged,) = await judge_probes([record], [case()], FakeAnswerJudge(0.8))
    assert judged.scores == {
        "probe_tool_f1": 1.0,
        "faithfulness": 0.8,
        "answer_accuracy": 0.8,
        "topic_adherence": 1.0,  # a criterion: held (score ≥ 0.5) or not
    }
    rows = {m.spec.id: m for m in scorecard([], {}, probes=[judged]).metrics}
    assert rows["faithfulness"].value == 0.8 and rows["faithfulness"].ok is False
    assert not rows["faithfulness"].spec.gate


class Broken(FakeAnswerJudge):
    async def faithfulness(self, question: str, answer: str, contexts: object) -> float:
        raise ValueError("the model returned nothing")

    async def holds(self, exchanges: object, criterion: str) -> bool:
        raise TimeoutError


async def test_a_judge_that_fails_leaves_no_score_and_is_named() -> None:
    record = await asked("Son 1.380 euros brutos al mes en 14 pagas.")
    judge: AnswerJudge = Broken()
    (judged,) = await judge_probes([record], [case()], judge)
    assert judged.scores["faithfulness"] is None
    row = next(m for m in scorecard([], {}, probes=[judged]).metrics if m.spec.id == "faithfulness")
    assert row.value is None and row.n == 0 and row.detail == "no score for R02"


async def test_scenario_runs_get_goal_rubric_style_and_topic_scores() -> None:
    scenarios = {s.id: s for s in load_scenarios(only=["S01", "S21"])}
    runs: list[RunRecord] = [await run_fake(s) for s in scenarios.values()]
    judged = await judge_runs(runs, scenarios, FakeAnswerJudge())
    s01, s21 = judged
    assert set(s01.scores) == {"topic_adherence", "style", "goal_accuracy", "rubric"}
    assert "goal_accuracy" not in s21.scores and s21.scores["rubric"] == 1.0  # no goal
    rows = {m.spec.id: m for m in scorecard(judged, scenarios).metrics}
    assert rows["goal_accuracy"].n == 1 and rows["rubric"].n == 2 and rows["style"].value == 1.0


async def test_exchanges_carry_each_assistant_turn_with_the_tools_it_called() -> None:
    (scenario,) = load_scenarios(only=["S05"])
    record = await run_fake(scenario)
    assert record.export is not None
    said: list[Exchange] = exchanges(record.export)
    assert said[0][0] == "ai" and said[1] == ("human", "Sí, me viene bien.", ())
    assert said[3] == ("human", "Antes de nada, ¿cuántas horas a la semana son?", ())
    assert said[4][0] == "ai" and said[4][2] == ("search_knowledge",)


def test_judge_selection_and_the_ragas_judge_runs_on_openai_only() -> None:
    assert judge_from("off") is None
    assert judge_from("fake") is not None and judge_from("fake").model_id == "fake"  # type: ignore[union-attr]
    with pytest.raises(ValueError, match="openai"):
        RagasJudge("groq/openai/gpt-oss-120b")


def test_the_live_scorecard_runs_end_to_end_for_free(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(scorecard_live, "BASELINES", tmp_path / "baselines")
    scenarios = load_scenarios(only=["S01"])
    cases = [c for c in load_cases() if c.id in {"R02", "R17"}]
    code = scorecard_live.execute(
        scenarios,
        cases,
        None,
        model="fake",
        simulator="fake",
        judge="fake",
        base_url=None,
        access_code=None,
        max_turns=2,
        out=tmp_path,
        yes=True,
        save_baseline=True,
    )
    out = capsys.readouterr().out
    assert code == 1  # the fake model books nothing: task success misses, and says so
    assert "| 0 | Runs completed: an export, no failed turn | 3/3 (100%)" in out
    (folder,) = tmp_path.glob("*-scorecard")
    written = {p.name for p in folder.iterdir()}
    assert {"scorecard.md", "scorecard.json", "probes.json", "probe-exports"} <= written
    assert any(name.endswith("-scenarios") for name in written)
    assert {p.name for p in (folder / "probe-exports").iterdir()} == {"R02.json", "R17.json"}
    assert '"export": null' in (folder / "probes.json").read_text()
    assert (tmp_path / "baselines" / "fake.json").exists()


async def test_an_empty_answer_is_not_judged_and_misses_its_facts() -> None:
    record = await asked("")
    (judged,) = await judge_probes([record], [case()], FakeAnswerJudge())
    assert set(judged.scores) == {"probe_tool_f1"}
    row = next(
        m for m in scorecard([], {}, probes=[judged]).metrics if m.spec.id == "fact_presence"
    )
    assert (row.k, row.n) == (0, 2)


async def test_a_failed_turn_is_a_completion_miss_not_a_quality_one() -> None:
    record = await asked("")
    failed = record.model_copy(
        update={"run": record.run.model_copy(update={"provider_failed": True})}
    )
    assert not failed.answered
    (judged,) = await judge_probes([failed], [case()], FakeAnswerJudge())
    assert judged.scores == {}
    rows = {m.spec.id: m for m in scorecard([], {}, probes=[judged]).metrics}
    assert rows["completed"].ok is False and rows["completed"].detail == "R02 (turn failed)"
    assert rows["fact_presence"].value is None
