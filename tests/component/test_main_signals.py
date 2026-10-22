"""The composition root builds the signal classifier only when a model is named for it."""

import pytest

from cafe_norte.conversation.signals import DecisionSignalAnalyzer, ModelSignalAnalyzer
from cafe_norte.main import _signals


def test_the_classifier_is_off_unless_a_signal_model_is_set() -> None:
    assert _signals({}) is None
    analyzer = _signals({"CAFE_NORTE_SIGNAL_MODEL": "openai/gpt-4o-mini", "OPENAI_API_KEY": "x"})
    assert isinstance(analyzer, ModelSignalAnalyzer)


def test_a_signal_model_without_its_key_is_refused_at_startup() -> None:
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        _signals({"CAFE_NORTE_SIGNAL_MODEL": "openai/gpt-4o-mini"})


def test_an_openrouter_selector_builds_the_decision_analyzer() -> None:
    analyzer = _signals(
        {"CAFE_NORTE_SIGNAL_MODEL": "openrouter/typesafe/jev-1.14", "OPENROUTER_API_KEY": "x"}
    )
    assert isinstance(analyzer, DecisionSignalAnalyzer)
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        _signals({"CAFE_NORTE_SIGNAL_MODEL": "openrouter/typesafe/jev-1.14"})
