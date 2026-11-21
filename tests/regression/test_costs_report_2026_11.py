"""Regression tests for cost-evidence disclosures reported against v0.14.1."""

from __future__ import annotations

import polars as pl
import pytest

from lacuna.costs import BorrowCostModel, stress


def _ledger(execution_times: list[int]) -> pl.DataFrame:
    rows = len(execution_times)
    return pl.DataFrame(
        {
            "decision_time": execution_times,
            "execution_time": execution_times,
            "instrument": [f"asset-{index}" for index in range(rows)],
            "side": ["buy"] * rows,
            "quantity": [10.0] * rows,
            "price": [100.0] * rows,
            "reference_price": [100.0] * rows,
            "gross_pnl": [60.0, 40.0, 55.0, 45.0][:rows],
        }
    )


def _net_sharpe(result: object) -> float:
    (row,) = result.table("stress_surface")  # type: ignore[attr-defined]
    return float(row["net_sharpe"])


def test_stress_sharpe_discloses_that_only_traded_periods_enter() -> None:
    """Net Sharpe ignores trade-free periods, so the result must say so.

    The same four trades spread over a longer calendar give an identical Sharpe: the ledger
    cannot represent the zero-return periods in between.
    """

    kwargs = {
        "spread_bps": (0.0,),
        "slippage_bps": (0.0,),
        "commission_bps": (0.0,),
        "capital": 10_000.0,
        "annualization": 252.0,
    }
    dense = stress(_ledger([0, 1, 2, 3]), **kwargs)  # type: ignore[arg-type]
    sparse = stress(_ledger([0, 50, 100, 150]), **kwargs)  # type: ignore[arg-type]

    assert _net_sharpe(dense) == pytest.approx(_net_sharpe(sparse))
    for result in (dense, sparse):
        assert any("only periods that contain at least one trade" in w for w in result.warnings)


def test_stress_without_annualization_has_no_period_basis_warning() -> None:
    result = stress(
        _ledger([0, 1, 2, 3]), spread_bps=(0.0,), slippage_bps=(0.0,), commission_bps=(0.0,)
    )
    assert not any("only periods that contain" in warning for warning in result.warnings)


def test_borrow_model_charges_by_declared_holding_days_not_position_state() -> None:
    """The stateless borrow model charges a sell row only over its declared interval.

    A sell that closes a long opens no short exposure; the documented contract is to declare
    ``holding_days = 0`` for it, which must cost exactly nothing.
    """

    trades = pl.DataFrame(
        {
            "decision_time": [0, 1, 2],
            "execution_time": [0, 1, 2],
            "instrument": ["A", "A", "B"],
            "side": ["buy", "sell", "sell"],
            "quantity": [10.0, -10.0, -20.0],
            "price": [100.0, 100.0, 50.0],
            "reference_price": [100.0, 100.0, 50.0],
            "borrow_rate": [0.365, 0.365, 0.365],
            "holding_days": [0.0, 0.0, 10.0],
        }
    )
    estimate = BorrowCostModel().estimate(trades)
    # Closing sell: zero days. Short sale: 1000 notional * 0.365 * 10 / 365 = 10.
    assert estimate.components["borrow"] == pytest.approx((0.0, 0.0, 10.0))
    assert "holding_days = 0" in (BorrowCostModel.__doc__ or "")
