"""Usage to euros with a versioned price table."""

from collections.abc import Sequence

from cafe_norte.domain.contracts import SessionId
from cafe_norte.observability.contracts import CostEstimate, PriceTable, UsageRecord


def estimate(
    session_id: SessionId, usage: Sequence[UsageRecord], prices: PriceTable
) -> CostEstimate:
    """Sum priced usage; list unpriced kinds instead of counting them as zero."""
    raise NotImplementedError
