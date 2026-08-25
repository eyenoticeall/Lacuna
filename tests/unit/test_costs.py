from __future__ import annotations

from collections.abc import Sequence

import polars as pl
import pytest

from lacuna.costs import (
    BorrowCostModel,
    CapacityScenario,
    CommissionModel,
    CompositeCostModel,
    CostEstimate,
    CostModel,
    CostScenario,
    ParticipationImpactModel,
    SlippageModel,
    SpreadModel,
    SquareRootImpactModel,
    VolatilitySlippageModel,
    break_even_cost,
    capacity_curve,
    liquidity_diagnostics,
    stress,
)
from lacuna.exceptions import DataContractError, MethodContractError


def _trades(
    *,
    quantity: Sequence[float] = (10.0, -20.0),
    price: Sequence[float] = (100.0, 50.0),
    reference_price: Sequence[float] | None = None,
    side: Sequence[str] = ("buy", "sell"),
    gross_pnl: Sequence[float] = (60.0, 40.0),
) -> pl.DataFrame:
    rows = len(quantity)
    references = price if reference_price is None else reference_price
    return pl.DataFrame(
        {
            "decision_time": list(range(rows)),
            "execution_time": list(range(rows)),
            "instrument": [f"asset-{index}" for index in range(rows)],
            "side": side,
            "quantity": quantity,
            "price": price,
            "reference_price": references,
            "gross_pnl": gross_pnl,
        }
    )


def test_cost_model_protocol_and_trade_contract() -> None:
    model = CommissionModel()
    assert isinstance(model, CostModel)
    assert model.required_fields() == (
        "decision_time",
        "execution_time",
        "instrument",
        "side",
        "quantity",
        "price",
        "reference_price",
    )

    with pytest.raises(DataContractError, match="signed quantity"):
        model.estimate(_trades(quantity=(10.0, 20.0)))
    with pytest.raises(DataContractError, match="decision_time exceeds"):
        model.estimate(_trades().with_columns(pl.Series("decision_time", [1, 2])))
    with pytest.raises(DataContractError, match="must be positive"):
        model.estimate(_trades(price=(100.0, 0.0)))


def test_commission_hand_calculation_and_zero_quantity_identity() -> None:
    estimate = CommissionModel(
        fixed_per_trade=1.0,
        per_unit=0.1,
        notional_bps=10.0,
        minimum=2.0,
    ).estimate(_trades())

    assert estimate.components["commission"] == pytest.approx((3.0, 4.0))
    assert estimate.total_cost == pytest.approx(7.0)
    assert estimate.known_total_cost == pytest.approx(7.0)
    assert estimate.unknown_rows == 0

    zero = CommissionModel(fixed_per_trade=5.0, minimum=10.0).estimate(_trades(quantity=(0.0, 0.0)))
    assert zero.total_cost == 0.0


def test_spread_supports_observed_and_assumed_quotes() -> None:
    assumed = SpreadModel(
        quoted_spread_bps=10.0,
        allow_on_observed_execution=True,
    ).estimate(_trades())
    assert assumed.components["spread"] == pytest.approx((0.5, 0.5))

    observed_trades = _trades().with_columns(
        pl.Series("bid", [99.0, 49.5]),
        pl.Series("ask", [101.0, 50.5]),
    )
    observed = SpreadModel(mode="full", allow_on_observed_execution=True).estimate(observed_trades)
    assert observed.components["spread"] == pytest.approx((20.0, 20.0))

    with pytest.raises(DataContractError, match="ask >= bid"):
        SpreadModel().estimate(observed_trades.with_columns(pl.Series("ask", [98.0, 48.0])))


def test_slippage_is_adverse_and_side_symmetric() -> None:
    trades = _trades(
        quantity=(10.0, -10.0),
        price=(100.0, 100.0),
        gross_pnl=(1.0, 1.0),
    )
    estimate = SlippageModel(
        fixed_per_unit=0.05,
        slippage_bps=5.0,
        allow_on_observed_execution=True,
    ).estimate(trades)
    assert estimate.components["slippage"] == pytest.approx((1.0, 1.0))


def test_observed_execution_and_existing_component_guards_prevent_double_application() -> None:
    observed = _trades(reference_price=(99.0, 51.0))
    with pytest.raises(MethodContractError, match="already be present"):
        SlippageModel(slippage_bps=1.0).estimate(observed)
    with pytest.raises(MethodContractError, match="already contains"):
        CommissionModel().estimate(_trades().with_columns(pl.lit(1.0).alias("commission")))

    allowed = SlippageModel(
        slippage_bps=1.0,
        allow_on_observed_execution=True,
    ).estimate(observed)
    assert allowed.total_cost == pytest.approx(0.2)


def test_volatility_slippage_requires_point_in_time_values() -> None:
    trades = _trades().with_columns(
        pl.Series("volatility", [0.2, 0.1]),
        pl.Series("volatility_available_time", [0, 1]),
    )
    estimate = VolatilitySlippageModel(
        coefficient=0.5,
        volatility_available_time="volatility_available_time",
        allow_on_observed_execution=True,
    ).estimate(trades)
    assert estimate.components["volatility_slippage"] == pytest.approx((100.0, 50.0))

    with pytest.raises(DataContractError, match="unavailable"):
        VolatilitySlippageModel(
            coefficient=0.5,
            volatility_available_time="volatility_available_time",
            allow_on_observed_execution=True,
        ).estimate(trades.with_columns(pl.Series("volatility_available_time", [1, 1])))


def test_participation_and_square_root_impact_match_planted_curves() -> None:
    trade = _trades(
        quantity=(100.0,),
        price=(10.0,),
        side=("buy",),
        gross_pnl=(100.0,),
    ).with_columns(
        pl.lit(10_000.0).alias("adv"),
        pl.lit(0.2).alias("volatility"),
    )
    square_root = SquareRootImpactModel(coefficient=0.5).estimate(trade)
    assert square_root.components["square_root_impact"] == pytest.approx((10.0,))

    linear = ParticipationImpactModel(
        coefficient=0.5,
        volume="adv",
        max_participation=0.005,
    ).estimate(trade)
    assert linear.components["participation_impact"] == pytest.approx((5.0,))
    assert {finding.code for finding in linear.findings} == {"COST_PARTICIPATION_LIMIT_EXCEEDED"}


def test_borrow_cost_handles_known_unknown_and_conservative_short_rates() -> None:
    trades = _trades().with_columns(
        pl.Series("borrow_rate", [None, 0.365], dtype=pl.Float64),
        pl.Series("holding_days", [10.0, 10.0]),
        pl.Series("borrow_available_time", [0, 1]),
    )
    known = BorrowCostModel(borrow_available_time="borrow_available_time").estimate(trades)
    assert known.components["borrow"] == pytest.approx((0.0, 10.0))

    unavailable = trades.with_columns(pl.Series("borrow_available_time", [0, 2]))
    unknown = BorrowCostModel(
        borrow_available_time="borrow_available_time",
        missing="unknown",
    ).estimate(unavailable)
    assert unknown.components["borrow"] == (0.0, None)
    assert unknown.total_cost is None
    assert unknown.known_total_cost == 0.0
    assert {finding.code for finding in unknown.findings} == {"COST_BORROW_UNKNOWN"}

    conservative = BorrowCostModel(
        borrow_available_time="borrow_available_time",
        missing="conservative",
        conservative_rate=0.73,
    ).estimate(unavailable)
    assert conservative.components["borrow"] == pytest.approx((0.0, 20.0))
    assert {finding.code for finding in conservative.findings} == {
        "COST_BORROW_CONSERVATIVE_ASSUMPTION"
    }


def test_composition_reconciles_components_and_rejects_ambiguity() -> None:
    estimate = CompositeCostModel(
        (
            CommissionModel(notional_bps=2.0),
            SpreadModel(quoted_spread_bps=4.0),
            SlippageModel(slippage_bps=3.0),
        )
    ).estimate(_trades())
    assert estimate.component_totals == pytest.approx(
        {"commission": 0.4, "spread": 0.4, "slippage": 0.6}
    )
    assert estimate.total_cost == pytest.approx(1.4)
    assert estimate.to_result().metrics["total_cost"] == pytest.approx(1.4)
    assert estimate.to_result().table("per_trade_costs")[0]["total_cost"] == pytest.approx(0.7)  # type: ignore[index]

    with pytest.raises(MethodContractError, match="names must be unique"):
        CompositeCostModel((CommissionModel(), CommissionModel()))
    with pytest.raises(MethodContractError, match="one currency"):
        CompositeCostModel(
            (CommissionModel(currency="USD"), SlippageModel(currency="EUR"))
        ).estimate(_trades())


def test_cost_estimate_preserves_unknowns_and_rejects_negative_values() -> None:
    estimate = CostEstimate(
        model_name="example",
        model_version=1,
        currency="USD",
        components={"example": (1.0, None)},
        assumptions={},
        input_fingerprint="sha256:test",
    )
    assert estimate.total_cost is None
    assert estimate.to_result().metrics["unknown_rows"] == 1
    with pytest.raises(DataContractError, match="non-negative"):
        CostEstimate(
            model_name="example",
            model_version=1,
            currency="USD",
            components={"example": (-1.0,)},
            assumptions={},
            input_fingerprint="sha256:test",
        )


def test_stress_grid_is_deterministic_monotonic_and_reconciled() -> None:
    kwargs = {
        "spread_bps": (0.0, 10.0),
        "slippage_bps": (0.0, 5.0),
        "commission_bps": (0.0,),
        "capital": 10_000.0,
        "annualization": 252.0,
    }
    first = stress(_trades(), **kwargs)  # type: ignore[arg-type]
    second = stress(_trades(), **kwargs)  # type: ignore[arg-type]
    assert first.table("stress_surface") == second.table("stress_surface")
    rows = first.table("stress_surface")
    assert len(rows) == 4  # type: ignore[arg-type]
    ordered = sorted(rows, key=lambda row: float(row["total_cost"]))  # type: ignore[arg-type, index]
    assert [row["net_pnl"] for row in ordered] == sorted(  # type: ignore[index]
        [row["net_pnl"] for row in ordered],  # type: ignore[index]
        reverse=True,
    )
    for row in rows:  # type: ignore[union-attr]
        assert row["gross_pnl"] - row["total_cost"] == pytest.approx(row["net_pnl"])
        assert sum(row["component_costs"].values()) == pytest.approx(row["total_cost"])


def test_stress_supports_explicit_correlated_scenarios() -> None:
    result = stress(
        _trades(),
        scenarios=(
            CostScenario("calm", spread_bps=2.0, slippage_bps=1.0),
            CostScenario("volatile", spread_bps=10.0, slippage_bps=8.0),
        ),
    )
    rows = result.table("stress_surface")
    assert [row["scenario"] for row in rows] == ["calm", "volatile"]  # type: ignore[index, union-attr]
    assert rows[1]["net_pnl"] < rows[0]["net_pnl"]  # type: ignore[index]


def test_stress_reuses_base_model_estimates_across_the_surface() -> None:
    class CountingModel:
        name = "custom"
        version = 1

        def __init__(self) -> None:
            self.calls = 0

        def required_fields(self) -> tuple[str, ...]:
            return CommissionModel().required_fields()

        def estimate(self, trades: object, market: object | None = None) -> CostEstimate:
            self.calls += 1
            reference = CommissionModel(notional_bps=1.0).estimate(trades, market)
            return CostEstimate(
                model_name=self.name,
                model_version=self.version,
                currency=reference.currency,
                components={self.name: reference.components["commission"]},
                assumptions={},
                input_fingerprint=reference.input_fingerprint,
            )

    model = CountingModel()
    result = stress(
        _trades(),
        spread_bps=(0.0, 5.0, 10.0),
        slippage_bps=(0.0, 5.0),
        base_models=(model,),
    )

    assert result.metrics["scenario_count"] == 6
    assert model.calls == 1


def test_break_even_cost_finds_planted_solution_and_does_not_extrapolate() -> None:
    result = break_even_cost(
        _trades(),
        lower_bps=0.0,
        upper_bps=1_000.0,
        tolerance_bps=1e-7,
    )
    assert result.metrics["status"] == "converged"
    assert result.metrics["solution_bps"] == pytest.approx(500.0, abs=1e-5)
    assert result.metrics["monotonic_decreasing"] is True

    no_crossing = break_even_cost(_trades(), upper_bps=100.0)
    assert no_crossing.metrics["status"] == "no_crossing"
    assert no_crossing.metrics["solution_bps"] is None
    assert {finding.code for finding in no_crossing.findings} == {"COST_BREAK_EVEN_NOT_BRACKETED"}


def test_liquidity_diagnostics_preserves_unknown_and_future_data() -> None:
    trades = _trades().with_columns(
        pl.Series("adv", [1_000.0, None], dtype=pl.Float64),
        pl.Series("adv_available_time", [0, 2]),
    )
    result = liquidity_diagnostics(
        trades,
        available_time="adv_available_time",
        classification_mode="point_in_time",
        max_participation=0.005,
    )
    assert result.metrics["known_rows"] == 1
    assert result.metrics["unknown_rows"] == 1
    assert result.metrics["breach_rows"] == 1
    assert {finding.code for finding in result.findings} == {
        "COST_LIQUIDITY_CONSTRAINT_BREACH",
        "COST_LIQUIDITY_UNKNOWN",
    }
    rows = result.table("liquidity")
    assert rows[0]["status"] == "breach"  # type: ignore[index]
    assert rows[1]["participation"] is None  # type: ignore[index]

    with pytest.raises(MethodContractError, match="requires available_time"):
        liquidity_diagnostics(
            trades,
            classification_mode="point_in_time",
        )


def test_capacity_curve_exposes_nonlinear_erosion_and_constraints() -> None:
    trades = _trades(
        quantity=(100.0,),
        price=(10.0,),
        side=("buy",),
        gross_pnl=(100.0,),
    ).with_columns(
        pl.lit(10_000.0).alias("adv"),
        pl.lit(0.2).alias("volatility"),
        pl.lit(0, dtype=pl.Int64).alias("market_available_time"),
    )
    result = capacity_curve(
        trades,
        capital=(10_000.0, 40_000.0),
        base_capital=10_000.0,
        scenarios=(CapacityScenario("base", impact_coefficient=0.5),),
        available_time="market_available_time",
        classification_mode="point_in_time",
        max_participation=0.02,
    )
    rows = result.table("capacity_curve")
    assert rows[0]["impact_cost"] == pytest.approx(10.0)  # type: ignore[index]
    assert rows[0]["net_return"] == pytest.approx(0.009)  # type: ignore[index]
    assert rows[1]["impact_cost"] == pytest.approx(80.0)  # type: ignore[index]
    assert rows[1]["net_return"] == pytest.approx(0.008)  # type: ignore[index]
    assert rows[1]["status"] == "constraint_breach"  # type: ignore[index]
    assert result.metrics["returns_single_capacity_number"] is False
    assert {finding.code for finding in result.findings} == {"COST_CAPACITY_CONSTRAINT_BREACH"}


def test_capacity_curve_does_not_fabricate_missing_liquidity() -> None:
    trades = _trades().with_columns(
        pl.Series("adv", [1_000.0, None], dtype=pl.Float64),
        pl.Series("volatility", [0.2, 0.1]),
    )
    result = capacity_curve(
        trades,
        capital=(10_000.0,),
        base_capital=10_000.0,
        scenarios=(CapacityScenario("base", impact_coefficient=0.5),),
        classification_mode="retrospective",
    )
    row = result.table("capacity_curve")[0]  # type: ignore[index]
    assert row["impact_cost"] is None
    assert row["total_cost"] is None
    assert row["net_return"] is None
    assert row["status"] == "unknown_liquidity"
    assert {finding.code for finding in result.findings} == {
        "COST_CAPACITY_RETROSPECTIVE",
        "COST_CAPACITY_UNKNOWN_LIQUIDITY",
    }
