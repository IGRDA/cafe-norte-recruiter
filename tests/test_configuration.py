"""Store configurations load from ``config/`` and refuse duplicates."""

from pathlib import Path

import pytest

from cafe_norte.domain.configuration import load_configurations
from cafe_norte.model.select import model_from_env
from tests.support import CONFIG_DIR


def test_both_stores_load_with_their_shifts() -> None:
    configurations = load_configurations(CONFIG_DIR)
    assert sorted(configurations) == ["arganzuela_barista_v1", "chamberi_barista_v1"]
    chamberi = configurations["chamberi_barista_v1"]  # type: ignore[index]
    assert [s.shift_id for s in chamberi.shifts] == ["morning", "afternoon"]
    assert chamberi.timezone == "Europe/Madrid"


def test_duplicate_ids_and_empty_directories_fail_startup(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no configuration files"):
        load_configurations(tmp_path)
    source = (CONFIG_DIR / "chamberi_barista_v1.yaml").read_text()
    (tmp_path / "a.yaml").write_text(source)
    (tmp_path / "b.yaml").write_text(source)
    with pytest.raises(ValueError, match="duplicate config_id"):
        load_configurations(tmp_path)


def test_model_selection_needs_a_known_provider_and_its_key() -> None:
    assert model_from_env("fake", {}).model_id == "fake"
    groq = model_from_env("groq/openai/gpt-oss-120b", {"GROQ_API_KEY": "k"})
    assert groq.model_id == "openai/gpt-oss-120b"
    with pytest.raises(ValueError, match="GROQ_API_KEY"):
        model_from_env("groq/openai/gpt-oss-120b", {})
    with pytest.raises(ValueError, match="unknown model selector"):
        model_from_env("openai/gpt-4o", {"OPENAI_API_KEY": "k"})
