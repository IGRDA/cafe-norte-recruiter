"""The scorecard (D48): tiers 0 and 1 are deterministic and gate; every fake scenario holds
them, so a prompt or runtime change that breaks one fails ``make check`` with the row named."""

import pytest
from evals.contracts import ReferenceTools, RunRecord
from evals.runner import load_scenarios, main, run_fake
from evals.scorecard import SPECS, render_markdown, scorecard
from evals.scorers import guess_language, leaks, model_turns, trajectory_misses, words

from cafe_norte.conversation import prompts


async def test_every_fake_scenario_holds_the_gated_rows() -> None:
    scenarios = load_scenarios()
    runs = [await run_fake(s) for s in scenarios]
    card = scorecard(runs, {s.id: s for s in scenarios})
    assert not card.gate_failures, render_markdown(card)
    measured = {m.spec.id for m in card.metrics if m.value is not None}
    assert {
        "export_valid",
        "turn_length",
        "tool_calls_accepted",
        "language_kept",
        "no_leak",
        "trajectory",
        "no_fabrication",
        "task_success",
    } <= measured
    assert card.prompt_version == prompts.PROMPT_VERSION


async def test_a_broken_trajectory_fails_its_row_and_names_the_case() -> None:
    (scenario,) = load_scenarios(only=["S01"])
    record = await run_fake(scenario)
    wants_more = scenario.model_copy(
        update={"reference_tools": ReferenceTools(never=("reserve_interview",))}
    )
    card = scorecard([record], {"S01": wants_more})
    (row,) = [m for m in card.metrics if m.spec.id == "trajectory"]
    assert row.ok is False and "S01: reserve_interview called" in row.detail
    assert row in card.gate_failures


def test_a_row_nobody_measured_is_not_run_and_never_fails() -> None:
    card = scorecard([], {})
    assert len(card.metrics) == len(SPECS) == 25
    assert all(m.value is None and m.ok is None for m in card.metrics)
    assert not card.gate_failures
    assert render_markdown(card).count("not run") == 25


async def test_the_baseline_gives_each_row_its_delta() -> None:
    (scenario,) = load_scenarios(only=["S03"])
    record = await run_fake(scenario)
    before = scorecard([record], {"S03": scenario})
    broken = record.model_copy(update={"export": None, "failure": "no_turn_end"})
    after = scorecard([record, broken], {"S03": scenario}, baseline=before)
    (row,) = [m for m in after.metrics if m.spec.id == "export_valid"]
    assert (row.k, row.n, row.baseline) == (1, 2, 1.0)
    assert "-50 pt" in render_markdown(after) and "S03: no_turn_end" in row.detail


async def test_judge_rows_report_and_never_gate() -> None:
    (scenario,) = load_scenarios(only=["S03"])
    record = (await run_fake(scenario)).model_copy(update={"scores": {"goal_accuracy": 0.5}})
    card = scorecard([record], {"S03": scenario})
    (row,) = [m for m in card.metrics if m.spec.id == "goal_accuracy"]
    assert row.ok is False and row.spec.tier == 2 and not row.spec.gate
    assert not card.gate_failures
    assert "below target" in render_markdown(card)


@pytest.mark.parametrize(
    ("text", "language"),
    [
        ("¿Qué días puedes trabajar en Chamberí?", "es"),
        ("What days can you work at the Chamberí store?", "en"),
        ("Café Norte, Chamberí.", None),
    ],
)
def test_the_language_is_guessed_from_function_words_not_accents(
    text: str, language: str | None
) -> None:
    assert guess_language(text) == language


@pytest.mark.parametrize(
    ("text", "found"),
    [
        ("Voy a llamar a reserve_interview ahora.", ["a tool name"]),
        ("Según offer_chamberi#salario son 1.380 euros.", ["a chunk id"]),
        ('Aquí tienes: {"slot_id": "x"}', ["JSON"]),
        ("Mi versión es ana_v17.", ["the prompt version"]),
        ("Son 1.380 euros brutos al mes en 14 pagas.", []),
    ],
)
def test_leaks_name_the_machinery_an_answer_gave_away(text: str, found: list[str]) -> None:
    assert leaks(text) == found


def test_twelve_words_of_the_system_prompt_said_aloud_are_a_leak() -> None:
    system = prompts.load("system").split("\n")
    line = next(line for line in system if words(line) >= 14)
    assert "the system prompt" in leaks(line)
    assert leaks("¿Tienes alguna duda sobre el puesto o la tienda?") == []


def test_a_trajectory_is_an_ordered_subsequence_plus_presence_and_absence() -> None:
    called = ("update_candidate", "search_knowledge", "confirm_brief", "end_session")
    held = ReferenceTools(
        in_order=("update_candidate", "confirm_brief", "end_session"),
        anywhere=("search_knowledge",),
        never=("reserve_interview",),
    )
    assert trajectory_misses(called, held) == []
    broken = ReferenceTools(
        in_order=("confirm_brief", "update_candidate"), never=("search_knowledge",)
    )
    assert trajectory_misses(called, broken) == [
        "update_candidate not in order",
        "search_knowledge called",
    ]


async def test_read_backs_and_fixed_replies_are_not_model_turns() -> None:
    (scenario,) = load_scenarios(only=["S01"])
    record: RunRecord = await run_fake(scenario)
    assert record.export is not None
    texts = [t.text for t in model_turns(record.export.transcript)]
    assert texts and not any(t.startswith(prompts.table("brief", "es")["intro"]) for t in texts)
    assert prompts.load("opening", "es").strip() not in texts


def test_the_cli_prints_the_scorecard_and_spends_nothing_live_without_yes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    main(["--suite", "scorecard", "--retriever", "lexical", "--only", "S03"])
    out = capsys.readouterr().out
    assert "| 0 | Run ended with a valid export | 1/1 (100%)" in out
    live = ["--suite", "scorecard", "--mode", "live", "--retriever", "lexical"]
    assert main(live) == 0
    out = capsys.readouterr().out
    assert "estimated spend" in out and "probes, judge openai/gpt-4o-mini" in out
    assert "Nothing was spent" in out
