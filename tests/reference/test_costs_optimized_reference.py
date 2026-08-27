from __future__ import annotations

import math
from collections import OrderedDict
from collections.abc import Sequence

import numpy as np
import polars as pl
import pytest

from lacuna.costs import (
    CapacityScenario,
    CostEstimate,
    CostScenario,
    TradeColumns,
    break_even_cost,
    capacity_curve,
    stress,
)


def _trades() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "decision_time": [0, 0, 1, 1, 2, 2],
            "execution_time": [0, 0, 1, 1, 2, 2],
            "instrument": ["a", "b", "a", "b", "a", "b"],
            "side": ["buy", "sell", "buy", "sell", "buy", "sell"],
            "quantity": [10.0, -20.0, 15.0, -10.0, 5.0, -30.0],
            "price": [100.0, 50.0, 101.0, 52.0, 99.0, 49.0],
            "reference_price": [100.0, 50.0, 101.0, 52.0, 99.0, 49.0],
            "gross_pnl": [30.0, 12.0, -5.0, 18.0, 14.0, 22.0],
            "adv": [10_000.0, 12_000.0, 11_000.0, 13_000.0, 9_000.0, 15_000.0],
            "volatility": [0.20, 0.18, 0.21, 0.19, 0.22, 0.17],
            "available_time": [0, 0, 1, 1, 2, 2],
        }
    )


class _FixedCostModel:
    name = "fixed_reference"
    version = 1

    def __init__(self, values: Sequence[float | None]) -> None:
        self._values = tuple(values)

    def required_fields(self) -> tuple[str, ...]:
        return TradeColumns().required()

    def estimate(self, trades: object, market: object | None = None) -> CostEstimate:
        del trades, market
        return CostEstimate(
            model_name=self.name,
            model_version=self.version,
            currency="USD",
            components={"fixed_reference": self._values},
            assumptions={},
            input_fingerprint="sha256:fixed-reference",
        )


def _literal_period_sums(periods: Sequence[int], values: np.ndarray) -> np.ndarray:
    grouped: OrderedDict[int, float] = OrderedDict()
    for period, value in zip(periods, values, strict=True):
        grouped[period] = grouped.get(period, 0.0) + float(value)
    return np.asarray(tuple(grouped.values()), dtype=np.float64)


def _literal_sharpe(values: np.ndarray, annualization: float) -> float:
    return float(np.mean(values) / np.std(values, ddof=1) * math.sqrt(annualization))


def test_cost_stress_optimized_aggregates_match_literal_row_rescan() -> None:
    frame = _trades()
    scenarios = (
        CostScenario("low", spread_bps=2.0, slippage_bps=1.0, commission_bps=0.5),
        CostScenario("high", spread_bps=12.0, slippage_bps=8.0, commission_bps=3.0),
    )
    fixed = np.asarray([0.1, 0.2, 0.3, 0.4, 0.5, 0.6], dtype=np.float64)
    result = stress(
        frame,
        scenarios=scenarios,
        base_models=(_FixedCostModel(fixed),),
        capital=25_000.0,
        annualization=252.0,
    )

    notional = np.abs(frame["quantity"].to_numpy()) * frame["price"].to_numpy()
    gross = frame["gross_pnl"].to_numpy()
    periods = frame["execution_time"].to_list()
    for actual, scenario in zip(result.table("stress_surface"), scenarios, strict=True):  # type: ignore[arg-type]
        commission = notional * scenario.commission_bps / 10_000.0
        spread = notional * scenario.spread_bps / 20_000.0
        slippage = notional * scenario.slippage_bps / 10_000.0
        per_trade = np.asarray(
            [
                float(commission[index] + spread[index] + slippage[index] + fixed[index])
                for index in range(frame.height)
            ],
            dtype=np.float64,
        )
        net_periods = _literal_period_sums(periods, gross - per_trade)
        expected_total = float(sum(float(value) for value in per_trade))
        assert actual["total_cost"] == pytest.approx(expected_total)
        assert actual["net_pnl"] == pytest.approx(float(gross.sum()) - expected_total)
        assert actual["net_sharpe"] == pytest.approx(_literal_sharpe(net_periods, 252.0))
        components = actual["component_costs"]
        assert components["commission"] == pytest.approx(float(commission.sum()))  # type: ignore[index]
        assert components["spread"] == pytest.approx(float(spread.sum()))  # type: ignore[index]
        assert components["slippage"] == pytest.approx(float(slippage.sum()))  # type: ignore[index]
        assert components["fixed_reference"] == pytest.approx(float(fixed.sum()))  # type: ignore[index]


def test_cost_stress_preaggregation_keeps_unknown_rows_out_of_known_total() -> None:
    frame = _trades()
    base = (0.1, None, 0.3, 0.4, 0.5, 0.6)
    result = stress(
        frame,
        scenarios=(CostScenario("one", commission_bps=10.0),),
        base_models=(_FixedCostModel(base),),
    )

    row = result.table("stress_surface")[0]  # type: ignore[index]
    notional = np.abs(frame["quantity"].to_numpy()) * frame["price"].to_numpy()
    expected = sum(
        float(base[index]) + float(notional[index]) * 10.0 / 10_000.0
        for index in range(frame.height)
        if base[index] is not None
    )
    assert row["known_cost_rows"] == frame.height - 1
    assert row["known_total_cost"] == pytest.approx(expected)
    assert row["total_cost"] is None
    assert row["net_pnl"] is None
    assert row["component_costs"]["fixed_reference"] is None  # type: ignore[index]


@pytest.mark.parametrize("metric", ["net_pnl", "net_return", "net_sharpe", "cagr"])
def test_break_even_preaggregation_matches_literal_trace(metric: str) -> None:
    frame = _trades()
    kwargs = {
        "metric": metric,
        "threshold": -10.0 if metric == "net_pnl" else -0.01,
        "capital": None if metric == "net_pnl" else 25_000.0,
        "annualization": 12.0 if metric in {"net_sharpe", "cagr"} else None,
        "upper_bps": 500.0,
    }
    result = break_even_cost(frame, **kwargs)  # type: ignore[arg-type]

    gross = frame["gross_pnl"].to_numpy()
    notional = np.abs(frame["quantity"].to_numpy()) * frame["price"].to_numpy()
    periods = frame["execution_time"].to_list()
    for row in result.table("solver_trace"):  # type: ignore[union-attr]
        cost_bps = float(row["cost_bps"])
        costs = notional * cost_bps / 10_000.0
        net = gross - costs
        if metric == "net_pnl":
            expected = float(net.sum())
        elif metric == "net_return":
            expected = float(net.sum()) / 25_000.0
        else:
            period_net = _literal_period_sums(periods, net) / 25_000.0
            if metric == "net_sharpe":
                expected = _literal_sharpe(period_net, 12.0)
            else:
                expected = float(np.prod(1.0 + period_net) ** (12.0 / period_net.size) - 1.0)
        assert row["metric_value"] == pytest.approx(expected, rel=1e-12, abs=1e-12)
        assert row["total_cost"] == pytest.approx(float(costs.sum()), rel=1e-12, abs=1e-12)


def test_capacity_scaling_identities_match_literal_trade_rescan() -> None:
    frame = _trades()
    scenarios = (
        CapacityScenario("base", impact_coefficient=0.4, spread_bps=2.0, slippage_bps=1.0),
        CapacityScenario("stressed", impact_coefficient=0.8, spread_bps=8.0, slippage_bps=5.0),
    )
    capital = (10_000.0, 25_000.0, 50_000.0)
    result = capacity_curve(
        frame,
        capital=capital,
        base_capital=10_000.0,
        scenarios=scenarios,
        available_time="available_time",
        classification_mode="point_in_time",
        max_participation=0.2,
        annualization=252.0,
    )

    quantity = np.abs(frame["quantity"].to_numpy())
    price = frame["price"].to_numpy()
    gross = frame["gross_pnl"].to_numpy()
    volume = frame["adv"].to_numpy()
    volatility = frame["volatility"].to_numpy()
    periods = frame["execution_time"].to_list()
    expected_rows = []
    for scenario in scenarios:
        for capital_value in capital:
            scale = capital_value / 10_000.0
            scaled_quantity = quantity * scale
            notional = quantity * price * scale
            participation = scaled_quantity / volume
            impact_fraction = scenario.impact_coefficient * volatility * np.sqrt(participation)
            impact = notional * impact_fraction
            spread = notional * scenario.spread_bps / 20_000.0
            slippage = notional * scenario.slippage_bps / 10_000.0
            total_cost = float(impact.sum() + spread.sum() + slippage.sum())
            net = gross * scale - impact - spread - slippage
            expected_rows.append(
                {
                    "impact_cost": float(impact.sum()),
                    "total_cost": total_cost,
                    "net_pnl": float(gross.sum() * scale) - total_cost,
                    "net_sharpe": _literal_sharpe(_literal_period_sums(periods, net), 252.0),
                    "median_participation": float(np.median(participation)),
                    "max_observed_participation": float(participation.max()),
                    "participation_breach_rows": int((participation > 0.2).sum()),
                }
            )

    for actual, expected in zip(
        result.table("capacity_curve"),
        expected_rows,
        strict=True,  # type: ignore[arg-type]
    ):
        for field, value in expected.items():
            assert actual[field] == pytest.approx(value, rel=1e-12, abs=1e-12)


def test_capacity_zero_quantity_does_not_turn_missing_market_data_into_unknown_cost() -> None:
    frame = _trades().with_columns(
        pl.Series("quantity", [0.0, -20.0, 15.0, -10.0, 5.0, -30.0]),
        pl.Series("adv", [None, 12_000.0, 11_000.0, 13_000.0, 9_000.0, 15_000.0]),
        pl.Series("volatility", [None, 0.18, 0.21, 0.19, 0.22, 0.17]),
    )
    result = capacity_curve(
        frame,
        capital=(10_000.0,),
        base_capital=10_000.0,
        scenarios=(CapacityScenario("base", impact_coefficient=0.4),),
        available_time="available_time",
        classification_mode="point_in_time",
    )

    row = result.table("capacity_curve")[0]  # type: ignore[index]
    assert result.metrics["unknown_liquidity_rows"] == 1
    assert row["impact_cost"] is not None
    assert row["total_cost"] is not None
    assert row["status"] == "ok"
