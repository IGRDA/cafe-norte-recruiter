"""What a paid command will cost, printed before it spends: the same price table the export
uses, conservative per-turn assumptions, and every model without a price named."""

import pytest
from evals.spend import (
    ANSWER_TOKENS_PER_TURN,
    EXPECTED_TURNS,
    estimate_spend,
    model_id,
)

from cafe_norte.observability.cost import load_prices

PRICES = load_prices()


def test_a_selector_names_the_model_the_price_table_knows() -> None:
    assert model_id("openai/gpt-4o-mini") == "gpt-4o-mini"
    assert model_id("groq/openai/gpt-oss-120b") == "openai/gpt-oss-120b"
    assert model_id("fake") == "fake"


def test_the_estimate_prices_every_run_simulator_and_judge() -> None:
    spend = estimate_spend(
        ["openai/gpt-4o-mini"] * 2, simulator="openai/gpt-4o-mini", judge=None, prices=PRICES
    )
    assert spend.unpriced == ()
    assert spend.runs == 2
    tokens_in, tokens_out = ANSWER_TOKENS_PER_TURN
    answering = 2 * EXPECTED_TURNS * (tokens_in * 0.15 + tokens_out * 0.60) / 1e6 / 1.1234
    assert spend.eur > answering  # the simulator costs something too
    assert spend.eur == pytest.approx(answering, rel=0.25)


def test_gpt_4o_costs_more_than_mini() -> None:
    mini = estimate_spend(["openai/gpt-4o-mini"], simulator=None, judge=None, prices=PRICES)
    full = estimate_spend(["openai/gpt-4o"], simulator=None, judge=None, prices=PRICES)
    assert full.eur > 10 * mini.eur
    assert full.unpriced == ()


def test_an_unpriced_model_is_named_not_counted_as_free() -> None:
    spend = estimate_spend(
        ["groq/openai/gpt-oss-120b"], simulator=None, judge="openai/gpt-4o", prices=PRICES
    )
    assert spend.unpriced == ("openai/gpt-oss-120b",)
    assert spend.eur > 0  # the judge is priced


def test_the_fake_model_is_free() -> None:
    spend = estimate_spend(["fake"], simulator="fake", judge="fake", prices=PRICES)
    assert (spend.eur, spend.unpriced) == (0.0, ())


def test_the_summary_line_says_what_it_assumed() -> None:
    spend = estimate_spend(["openai/gpt-4o"] * 24, simulator=None, judge=None, prices=PRICES)
    line = spend.describe()
    assert "24 runs" in line and "€" in line and f"{EXPECTED_TURNS} turns" in line
