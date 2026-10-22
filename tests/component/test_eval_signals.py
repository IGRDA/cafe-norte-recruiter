"""The signals suite's tooling over fakes: the case sets, each system, the command and
the held-out generator. The scores are unit tests (unit/test_eval_signals_report.py)."""

import argparse
import json
from pathlib import Path

import pytest
from evals.signals import (
    JevClassifier,
    LlmClassifier,
    ProductionClassifier,
    RegexClassifier,
    estimate_eur,
    llm_prompt,
    load_cases,
    signals_main,
)
from evals.signals_report import (
    REQUESTED,
    SHOULD_STAY,
)

from cafe_norte.conversation.signals import QUESTIONS
from cafe_norte.model.contracts import (
    ChoiceAnswer,
    Decision,
    ModelError,
    ModelEvent,
    ModelFinished,
    ModelText,
    ModelUsage,
)
from cafe_norte.model.fake import FakeDecisionModel, FakeModel
from cafe_norte.observability.cost import load_prices
from tests.support.evals import signal_case

PRICES = load_prices()
CASES = load_cases()


# ---- the fixture ---------------------------------------------------------------------------------


def test_the_fixture_covers_every_label_kind_and_language() -> None:
    assert len({c.id for c in CASES}) == len(CASES) >= 100
    assert {c.sentiment for c in CASES} == {"neutral", "positive", "frustrated", "uncertain"}
    assert {c.kind for c in CASES} == SHOULD_STAY | REQUESTED | {"written_other"}
    assert {c.session_language for c in CASES} == {"es", "en"}
    for sentiment in ("frustrated", "uncertain", "positive"):
        assert sum(c.sentiment == sentiment for c in CASES) >= 10


def test_a_kind_decides_whether_the_case_switches() -> None:
    for c in CASES:
        assert c.switch == (c.kind not in SHOULD_STAY), c.id


def test_only_selects_cases_and_rejects_unknown_ids() -> None:
    assert [c.id for c in load_cases(only=["es-01", "en-01"])] == ["es-01", "en-01"]
    with pytest.raises(ValueError, match="nope"):
        load_cases(only=["nope"])


# ---- the systems ---------------------------------------------------------------------------------


def decided(sentiment: str, language: str, p: float) -> Decision:
    """Jev's verdict on a Spanish-session case: ``language`` at ``p``, Spanish the rest."""
    probabilities = {"es": 1 - p, language: p} if language != "es" else {"es": p}
    return Decision(
        answers={
            "sentiment": ChoiceAnswer(choice=sentiment, probabilities={sentiment: 0.85}),
            "reply_language": ChoiceAnswer(choice=language, probabilities=probabilities),
        },
        model_id="typesafe/jev-1.14-20261014",
        input_tokens=300,
        output_tokens=0,
    )


async def test_jev_answers_both_questions_with_probabilities_in_languages() -> None:
    model = FakeDecisionModel([decided("frustrated", "en", 0.92)])
    model.model_id = "typesafe/jev-1.14"
    found = await JevClassifier(model, PRICES).classify(signal_case(), 1)
    assert (found.sentiment, found.reply_language, found.error) == ("frustrated", "en", None)
    assert found.language_probabilities == {"es": pytest.approx(0.08), "en": 0.92}
    assert found.cost_eur is not None and found.cost_eur > 0
    assert model.states[0] == {
        "session_language": "es",
        "ana_said": "¿Qué días puedes trabajar?",
        "candidate_said": "De lunes a viernes.",
    }


async def test_jev_failing_is_recorded_not_raised() -> None:
    model = FakeDecisionModel([ModelError("HTTP 402", code="provider_rejected")])
    found = await JevClassifier(model, PRICES).classify(signal_case(), 1)
    assert found.error == "provider_rejected" and found.sentiment is None


async def test_regex_switches_on_a_request_and_not_on_a_mention() -> None:
    regex = RegexClassifier()
    asked = await regex.classify(signal_case(text="¿Podemos hablar en inglés, por favor?"), 1)
    mentioned = await regex.classify(
        signal_case(text="¿Hace falta saber inglés para el puesto?"), 1
    )
    assert (asked.reply_language, mentioned.reply_language) == ("en", "es")
    assert asked.sentiment is None


def reply(text: str) -> FakeModel:
    usage = ModelUsage(input_tokens=600, output_tokens=20, model_id="gpt-4o-mini-2024-07-18")
    events: list[ModelEvent] = [ModelText(text=text), usage, ModelFinished(reason="stop")]
    model = FakeModel([events])
    model.model_id = "gpt-4o-mini"
    return model


async def test_the_llm_system_parses_a_fenced_answer_and_prices_it() -> None:
    model = reply('```json\n{"sentiment": "uncertain", "reply_language": "en"}\n```')
    found = await LlmClassifier(model, PRICES).classify(signal_case(), 1)
    assert (found.sentiment, found.reply_language, found.error) == ("uncertain", "en", None)
    assert found.cost_eur is not None and found.cost_eur > 0
    sent = model.calls[0]
    assert json.loads(sent[1].content)["candidate_said"] == "De lunes a viernes."


async def test_the_llm_system_records_a_malformed_answer() -> None:
    found = await LlmClassifier(reply("frustrated"), PRICES).classify(signal_case(), 1)
    assert found.error == "malformed" and found.sentiment is None


async def test_the_production_system_keeps_the_evidence_rule() -> None:
    backed = reply('{"sentiment": "frustrated", "evidence_text": "lunes"}')
    unbacked = reply('{"sentiment": "frustrated", "evidence_text": "never said"}')
    assert (await ProductionClassifier(backed, PRICES).classify(signal_case(), 1)).sentiment == (
        "frustrated"
    )
    dropped = await ProductionClassifier(unbacked, PRICES).classify(signal_case(), 1)
    assert (dropped.sentiment, dropped.error) == ("neutral", None)


def test_the_llm_is_asked_every_option_jev_is_asked() -> None:
    prompt = llm_prompt()
    for question in QUESTIONS.values():
        assert question.instructions in prompt
        for option, meaning in question.criteria.items():
            assert f"- {option}: {meaning}" in prompt


# ---- the command ---------------------------------------------------------------------------------


def args(tmp_path: Path, *, yes: bool, systems: list[str]) -> argparse.Namespace:
    return argparse.Namespace(
        only=["es-49", "es-67"],
        cases="dev",
        systems=systems,
        repeat=1,
        signal_model="openai/gpt-4o-mini",
        yes=yes,
        out=str(tmp_path),
    )


def test_without_yes_only_the_free_regex_runs_and_nothing_is_written(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert signals_main(args(tmp_path, yes=False, systems=["regex", "jev"]), env={}) == 0
    out = capsys.readouterr().out
    assert "Nothing paid was called" in out and "| regex |" in out
    assert list(tmp_path.iterdir()) == []


def test_jev_without_its_key_stops_before_calling(tmp_path: Path) -> None:
    assert signals_main(args(tmp_path, yes=True, systems=["jev"]), env={}) == 2


def test_the_estimate_prices_the_llm_and_jev() -> None:
    eur, unpriced = estimate_eur(["production", "llm", "jev"], "openai/gpt-4o-mini", 100, PRICES)
    assert unpriced == [] and 0 < eur < 0.05


# ---- the held-out generator ----------------------------------------------------------------------


def written(*texts: str) -> list[ModelEvent]:
    lines = [{"ana": "¿Qué días puedes trabajar?", "text": t} for t in texts]
    return [ModelText(text=json.dumps({"cases": lines})), ModelFinished(reason="stop")]


def checked(*fits: bool) -> list[ModelEvent]:
    return [ModelText(text=json.dumps({"fits": list(fits)})), ModelFinished(reason="stop")]


async def test_the_generator_keeps_lines_that_fit_with_the_cells_labels() -> None:
    from evals.signals_generate import generate

    model = FakeModel(
        [
            written("Can we switch to English?", "Prefiero el español.", "English, please."),
            checked(True, False, True),
            written("Can we continue in Spanish?"),
            checked(True),
        ]
    )
    cases = await generate(model, grid=(("explicit", "neutral", 1),))
    assert [(c.session_language, c.text, c.reply_language) for c in cases] == [
        ("es", "Can we switch to English?", "en"),
        ("en", "Can we continue in Spanish?", "es"),
    ]
    assert all(c.kind == "explicit" and c.sentiment == "neutral" for c in cases)
    writer_prompt = model.calls[0][1].content
    assert "continue in English instead of Spanish" in writer_prompt


async def test_a_cell_with_no_fitting_line_stops_the_generation() -> None:
    from evals.signals_generate import generate

    model = FakeModel([written("Hola."), checked(False)])
    with pytest.raises(ValueError, match="no line fits"):
        await generate(model, grid=(("stay", "neutral", 1),))


def test_the_committed_held_out_set_loads_and_covers_every_kind() -> None:
    from evals.signals import CASE_SETS

    held_out = load_cases(CASE_SETS["heldout"])
    assert len(held_out) >= 70
    assert {c.kind for c in held_out} == SHOULD_STAY | REQUESTED | {"written_other"}
    assert not {c.id for c in held_out} & {c.id for c in CASES}
