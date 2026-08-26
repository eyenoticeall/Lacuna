from __future__ import annotations

import polars as pl
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from lacuna.costs import (
    CommissionModel,
    CompositeCostModel,
    SlippageModel,
    SpreadModel,
    SquareRootImpactModel,
)


def _trade(*, quantity: float, side: str, price: float = 100.0) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "decision_time": [0],
            "execution_time": [0],
            "instrument": ["asset"],
            "side": [side],
            "quantity": [quantity],
            "price": [price],
            "reference_price": [price],
        }
    )


@settings(deadline=None)
@given(
    quantity=st.floats(min_value=0.0, max_value=1_000_000.0, allow_nan=False),
    low_bps=st.floats(min_value=0.0, max_value=100.0, allow_nan=False),
    increment=st.floats(min_value=0.0, max_value=100.0, allow_nan=False),
)
def test_non_negative_commission_is_monotonic(
    quantity: float,
    low_bps: float,
    increment: float,
) -> None:
    trades = _trade(quantity=quantity, side="buy")
    low = CommissionModel(notional_bps=low_bps).estimate(trades).total_cost
    high = CommissionModel(notional_bps=low_bps + increment).estimate(trades).total_cost

    assert low is not None
    assert high is not None
    assert high >= low


@settings(deadline=None)
@given(
    quantity=st.floats(min_value=0.0, max_value=1_000_000.0, allow_nan=False),
    bps=st.floats(min_value=0.0, max_value=1_000.0, allow_nan=False),
)
def test_adverse_slippage_has_buy_sell_sign_symmetry(quantity: float, bps: float) -> None:
    buy = SlippageModel(slippage_bps=bps).estimate(_trade(quantity=quantity, side="buy"))
    sell = SlippageModel(slippage_bps=bps).estimate(_trade(quantity=-quantity, side="sell"))

    assert buy.total_cost == pytest.approx(sell.total_cost)


@settings(deadline=None)
@given(
    quantity=st.floats(min_value=0.0, max_value=100_000.0, allow_nan=False),
    commission_bps=st.floats(min_value=0.0, max_value=100.0, allow_nan=False),
    spread_bps=st.floats(min_value=0.0, max_value=100.0, allow_nan=False),
    slippage_bps=st.floats(min_value=0.0, max_value=100.0, allow_nan=False),
)
def test_component_sum_always_reconciles(
    quantity: float,
    commission_bps: float,
    spread_bps: float,
    slippage_bps: float,
) -> None:
    estimate = CompositeCostModel(
        (
            CommissionModel(notional_bps=commission_bps),
            SpreadModel(quoted_spread_bps=spread_bps),
            SlippageModel(slippage_bps=slippage_bps),
        )
    ).estimate(_trade(quantity=quantity, side="buy"))

    assert estimate.total_cost == pytest.approx(
        sum(value for value in estimate.component_totals.values() if value is not None)
    )


@settings(deadline=None)
@given(
    quantity=st.floats(min_value=0.0, max_value=10_000.0, allow_nan=False),
    scale=st.floats(min_value=1.0, max_value=10.0, allow_nan=False),
    coefficient=st.floats(min_value=0.0, max_value=2.0, allow_nan=False),
)
def test_square_root_impact_cost_is_monotonic_in_trade_size(
    quantity: float,
    scale: float,
    coefficient: float,
) -> None:
    def with_market(size: float) -> pl.DataFrame:
        return _trade(quantity=size, side="buy").with_columns(
            pl.lit(1_000_000.0).alias("adv"),
            pl.lit(0.2).alias("volatility"),
        )

    low = SquareRootImpactModel(coefficient=coefficient).estimate(with_market(quantity))
    high = SquareRootImpactModel(coefficient=coefficient).estimate(with_market(quantity * scale))

    assert low.total_cost is not None
    assert high.total_cost is not None
    assert high.total_cost >= low.total_cost
