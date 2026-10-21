"""Usage to euros with a versioned price table."""

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import yaml

from cafe_norte.domain.contracts import SessionId
from cafe_norte.observability.contracts import CostEstimate, Price, PriceTable, UsageRecord

PRICES_FILE = Path(__file__).parent / "prices" / "v1.yaml"


def load_prices(path: Path = PRICES_FILE) -> PriceTable:
    """Read the price file; its dollar prices become euros at the rate it records."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    usd_per_eur = float(raw["usd_per_eur"])
    verified_on = raw["verified_on"]
    return PriceTable(
        version=str(raw["version"]),
        verified_on=datetime(verified_on.year, verified_on.month, verified_on.day, tzinfo=UTC),
        prices=tuple(
            Price(
                kind=entry["kind"],
                unit_detail=entry["unit_detail"],
                eur_per_unit=float(entry["usd_per_unit"]) / usd_per_eur,
            )
            for entry in raw["prices"]
        ),
    )


def estimate(
    session_id: SessionId, usage: Sequence[UsageRecord], prices: PriceTable
) -> CostEstimate:
    """Sum priced usage; list unpriced kinds instead of counting them as zero."""
    rates = {(p.kind, p.unit_detail): p.eur_per_unit for p in prices.prices}
    total = 0.0
    missing: list[str] = []
    for record in usage:
        rate = rates.get((record.kind, record.unit_detail))
        if rate is None:
            label = f"{record.kind}:{record.unit_detail}"
            if label not in missing:
                missing.append(label)
            continue
        total += record.quantity * rate
    return CostEstimate(
        session_id=session_id,
        marginal_eur=total,
        missing_prices=tuple(missing),
        price_table_version=prices.version,
    )
