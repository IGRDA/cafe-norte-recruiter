"""What a paid command will cost, before it spends anything.

Synthetic usage from conservative per-turn assumptions, priced with the same table and the
same function the export uses (``observability.cost``). A model with no price is named, never
counted as free; the fake model is free."""

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from cafe_norte.domain.contracts import SessionId
from cafe_norte.observability.contracts import PriceTable, UsageRecord
from cafe_norte.observability.cost import estimate

# Assumptions, deliberately high (docs/architecture.md). A candidate turn is about two model
# rounds, each sending the system prompt, the tool schemas and the recent turns.
EXPECTED_TURNS = 14  # candidate lines in a full interview with a brief and a booking
ANSWER_TOKENS_PER_TURN = (12_000, 200)  # (input, output) for the answering model
SIMULATOR_TOKENS_PER_TURN = (1_200, 60)
JUDGE_TOKENS_PER_RUN = (8_000, 300)


class Spend(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    runs: int
    eur: float
    unpriced: tuple[str, ...]  # model ids with no price: their tokens are not in ``eur``
    price_table_version: str
    basis: str = f"assumes {EXPECTED_TURNS} turns a run"

    def describe(self) -> str:
        unpriced = f"; NO PRICE for {', '.join(self.unpriced)}" if self.unpriced else ""
        return (
            f"estimated spend: €{self.eur:.2f} for {self.runs} runs "
            f"({self.basis}, prices {self.price_table_version}){unpriced}"
        )


def model_id(selector: str) -> str:
    """``provider/model`` → the model id the provider and the price table use."""
    return selector.split("/", 1)[1] if "/" in selector else selector


def estimate_spend(
    answering: Sequence[str], *, simulator: str | None, judge: str | None, prices: PriceTable
) -> Spend:
    """``answering``: one model selector per run."""
    usage: list[UsageRecord] = []
    for selector in answering:
        usage += _tokens(selector, ANSWER_TOKENS_PER_TURN, EXPECTED_TURNS)
        if simulator is not None:
            usage += _tokens(simulator, SIMULATOR_TOKENS_PER_TURN, EXPECTED_TURNS)
        if judge is not None:
            usage += _tokens(judge, JUDGE_TOKENS_PER_RUN, 1)
    return _priced(usage, prices, runs=len(answering))


Calls = tuple[str, tuple[int, int], int]  # model selector, (input, output) tokens a call, calls


def estimate_calls(calls: Sequence[Calls], prices: PriceTable, *, runs: int, basis: str) -> Spend:
    """Spend for model calls counted up front (testset generation, probes, judges, D48)."""
    usage = [u for selector, tokens, count in calls for u in _tokens(selector, tokens, count)]
    return _priced(usage, prices, runs=runs, basis=basis)


def _priced(usage: list[UsageRecord], prices: PriceTable, *, runs: int, basis: str = "") -> Spend:
    cost = estimate(SessionId("estimate"), usage, prices)
    unpriced = tuple(dict.fromkeys(_model_of(label) for label in cost.missing_prices))
    return Spend(
        runs=runs,
        eur=cost.marginal_eur,
        unpriced=unpriced,
        price_table_version=cost.price_table_version,
        **({"basis": basis} if basis else {}),
    )


def _tokens(selector: str, per_turn: tuple[int, int], turns: int) -> list[UsageRecord]:
    if selector == "fake":
        return []
    model = model_id(selector)
    return [
        UsageRecord(
            session_id=SessionId("estimate"),
            turn_id=None,
            kind="llm_tokens",
            quantity=float(count * turns),
            unit_detail=f"{model}:{direction}",
            estimated=True,
        )
        for count, direction in zip(per_turn, ("input", "output"), strict=True)
        if count  # an embedding has no output to price
    ]


def _model_of(label: str) -> str:
    """``llm_tokens:<model>:<direction>`` → ``<model>`` (a model id may contain ``/``)."""
    return label.split(":", 1)[1].rsplit(":", 1)[0]
