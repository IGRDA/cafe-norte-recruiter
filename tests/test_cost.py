"""Usage to euros: the pure estimate, and the shipped price table."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from cafe_norte.domain.contracts import SessionId, TurnId
from cafe_norte.observability.contracts import Price, PriceTable, UsageKind, UsageRecord
from cafe_norte.observability.cost import estimate, load_prices
from cafe_norte.voice.contracts import TTS_MODEL

SID = SessionId("s1")

TABLE = PriceTable(
    version="test-1",
    verified_on=datetime(2026, 10, 21, tzinfo=UTC),
    prices=(
        Price(kind="llm_tokens", unit_detail="m:input", eur_per_unit=0.000001),
        Price(kind="llm_tokens", unit_detail="m:output", eur_per_unit=0.000004),
        Price(kind="stt_seconds", unit_detail="stt", eur_per_unit=0.001),
    ),
)


def usage(kind: UsageKind, detail: str, quantity: float, *, estimated: bool = False) -> UsageRecord:
    return UsageRecord(
        session_id=SID,
        turn_id=TurnId("t1"),
        kind=kind,
        quantity=quantity,
        unit_detail=detail,
        estimated=estimated,
    )


def test_priced_usage_is_summed() -> None:
    result = estimate(
        SID,
        [usage("llm_tokens", "m:input", 1000), usage("llm_tokens", "m:output", 500)],
        TABLE,
    )
    assert result.marginal_eur == pytest.approx(0.003)
    assert result.missing_prices == ()
    assert result.price_table_version == "test-1"


def test_unpriced_usage_is_listed_not_counted_as_zero() -> None:
    result = estimate(
        SID,
        [usage("llm_tokens", "m:input", 1000), usage("llm_tokens", "other:input", 9000)],
        TABLE,
    )
    assert result.marginal_eur == pytest.approx(0.001)
    assert result.missing_prices == ("llm_tokens:other:input",)


def test_each_missing_price_is_listed_once() -> None:
    result = estimate(
        SID,
        [usage("tts_characters", "tts", 10), usage("tts_characters", "tts", 20)],
        TABLE,
    )
    assert result.missing_prices == ("tts_characters:tts",)


def test_no_usage_costs_nothing() -> None:
    result = estimate(SID, [], TABLE)
    assert result.marginal_eur == 0.0
    assert result.missing_prices == ()


def test_shipped_table_prices_every_provider_in_use() -> None:
    table = load_prices()
    assert table.currency == "EUR"
    assert table.verified_on.tzinfo is not None
    priced = {(p.kind, p.unit_detail) for p in table.prices}
    assert priced >= {
        ("llm_tokens", "gpt-4o-mini:input"),
        ("llm_tokens", "gpt-4o-mini:output"),
        ("stt_seconds", "nova-3"),
        ("tts_characters", TTS_MODEL),
        ("media_participant_minutes", "daily"),
    }
    assert all(p.eur_per_unit > 0 for p in table.prices)


def test_shipped_table_converts_dollars_at_its_recorded_rate(tmp_path: Path) -> None:
    path = tmp_path / "prices.yaml"
    path.write_text(
        "version: t\n"
        "verified_on: 2026-10-21\n"
        "usd_per_eur: 2.0\n"
        "prices:\n"
        "  - {kind: stt_seconds, unit_detail: stt, usd_per_unit: 0.01, source: https://example.com}\n",
        encoding="utf-8",
    )
    table = load_prices(path)
    assert table.prices[0].eur_per_unit == pytest.approx(0.005)
    assert table.verified_on == datetime(2026, 10, 21, tzinfo=UTC)
