"""Transparent transaction-cost, liquidity, and capacity scenario analysis."""

from __future__ import annotations

import itertools
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Literal, Protocol, TypeAlias, cast, runtime_checkable

import numpy as np
import numpy.typing as npt
import polars as pl

from lacuna._frames import (
    FrameDiagnostics,
    eager_frame,
    frame_records,
    require_identifier,
    require_no_nulls,
    require_numeric,
    require_time_key,
)
from lacuna.exceptions import DataContractError, MethodContractError
from lacuna.experiment import fingerprint
from lacuna.types import AnalysisResult, Finding, FindingState, JsonValue, ResultMetadata, Severity

QuantityConvention: TypeAlias = Literal["signed", "absolute"]
SpreadMode: TypeAlias = Literal["half", "full"]
MissingBorrowPolicy: TypeAlias = Literal["raise", "unknown", "conservative"]
LiquidityMode: TypeAlias = Literal["point_in_time", "retrospective"]
BreakEvenMetric: TypeAlias = Literal["net_pnl", "net_return", "net_sharpe", "cagr"]
FloatArray: TypeAlias = npt.NDArray[np.float64]


class CostUnit(StrEnum):
    """Unit of every built-in monetary estimate."""

    CURRENCY = "currency"


def _trimmed(value: str, *, name: str) -> str:
    if not value or value.strip() != value:
        raise MethodContractError(f"{name} must be a non-empty trimmed string")
    return value


def _non_negative(value: float, *, name: str) -> float:
    if not math.isfinite(value) or value < 0.0:
        raise MethodContractError(f"{name} must be finite and non-negative")
    return float(value)


def _positive(value: float, *, name: str) -> float:
    if not math.isfinite(value) or value <= 0.0:
        raise MethodContractError(f"{name} must be finite and positive")
    return float(value)


def _freeze_json(value: JsonValue) -> JsonValue:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, tuple):
        return tuple(_freeze_json(item) for item in value)
    if isinstance(value, float) and not math.isfinite(value):
        raise DataContractError("cost assumptions must not contain NaN or infinity")
    return value


def _freeze_mapping(value: Mapping[str, JsonValue]) -> Mapping[str, JsonValue]:
    frozen = _freeze_json(value)
    if not isinstance(frozen, Mapping):  # pragma: no cover - protected by the type contract
        raise TypeError("expected a JSON-compatible mapping")
    return frozen


@dataclass(frozen=True, slots=True)
class TradeColumns:
    """Semantic columns for Lacuna's normalized trade contract."""

    decision_time: str = "decision_time"
    execution_time: str = "execution_time"
    instrument: str = "instrument"
    side: str = "side"
    quantity: str = "quantity"
    price: str = "price"
    reference_price: str = "reference_price"

    def __post_init__(self) -> None:
        values = (
            self.decision_time,
            self.execution_time,
            self.instrument,
            self.side,
            self.quantity,
            self.price,
            self.reference_price,
        )
        for value in values:
            _trimmed(value, name="trade column")
        if len(set(values)) != len(values):
            raise MethodContractError("trade semantic columns must be unique")

    def required(self) -> tuple[str, ...]:
        """Return the complete normalized trade schema."""

        return (
            self.decision_time,
            self.execution_time,
            self.instrument,
            self.side,
            self.quantity,
            self.price,
            self.reference_price,
        )

    def to_parameters(self) -> dict[str, JsonValue]:
        return {
            "decision_time": self.decision_time,
            "execution_time": self.execution_time,
            "instrument": self.instrument,
            "side": self.side,
            "quantity": self.quantity,
            "price": self.price,
            "reference_price": self.reference_price,
        }


@dataclass(frozen=True, slots=True)
class CostEstimate:
    """Immutable per-trade cost components with explicit unknown values."""

    model_name: str
    model_version: int
    currency: str
    components: Mapping[str, tuple[float | None, ...]]
    assumptions: Mapping[str, JsonValue]
    input_fingerprint: str
    findings: tuple[Finding, ...] = ()
    unit: CostUnit = CostUnit.CURRENCY

    def __post_init__(self) -> None:
        _trimmed(self.model_name, name="model_name")
        _trimmed(self.currency, name="currency")
        _trimmed(self.input_fingerprint, name="input_fingerprint")
        if self.model_version < 1:
            raise MethodContractError("model_version must be positive")
        if not self.components:
            raise MethodContractError("components must contain at least one named component")
        lengths: set[int] = set()
        normalized: dict[str, tuple[float | None, ...]] = {}
        for name, values in self.components.items():
            _trimmed(name, name="component name")
            costs: list[float | None] = []
            for value in values:
                if value is None:
                    costs.append(None)
                elif not math.isfinite(value) or value < 0.0:
                    raise DataContractError("component costs must be finite non-negative values")
                else:
                    costs.append(float(value))
            normalized[name] = tuple(costs)
            lengths.add(len(costs))
        if len(lengths) != 1:
            raise DataContractError("all cost components must have the same row count")
        if any(not isinstance(finding, Finding) for finding in self.findings):
            raise TypeError("findings must contain Finding values")
        object.__setattr__(self, "components", MappingProxyType(normalized))
        object.__setattr__(self, "assumptions", _freeze_mapping(self.assumptions))
        object.__setattr__(self, "findings", tuple(self.findings))

    @property
    def trade_count(self) -> int:
        """Number of rows aligned across components."""

        return len(next(iter(self.components.values())))

    @property
    def per_trade_costs(self) -> tuple[float | None, ...]:
        """Sum components row by row while preserving unknown totals."""

        rows: list[float | None] = []
        for index in range(self.trade_count):
            values = [component[index] for component in self.components.values()]
            rows.append(
                None
                if any(value is None for value in values)
                else sum(cast(float, value) for value in values)
            )
        return tuple(rows)

    @property
    def unknown_rows(self) -> int:
        """Number of rows whose all-in cost is not known."""

        return sum(value is None for value in self.per_trade_costs)

    @property
    def known_total_cost(self) -> float:
        """Sum known row costs without disguising incomplete coverage."""

        return float(sum(value for value in self.per_trade_costs if value is not None))

    @property
    def total_cost(self) -> float | None:
        """Complete total, or ``None`` when any row is unknown."""

        return None if self.unknown_rows else self.known_total_cost

    @property
    def component_totals(self) -> Mapping[str, float | None]:
        """Complete totals for each named component."""

        return MappingProxyType(
            {
                name: None
                if any(value is None for value in values)
                else float(sum(cast(float, value) for value in values))
                for name, values in self.components.items()
            }
        )

    def to_result(self) -> AnalysisResult:
        """Convert the estimate to Lacuna's shared evidence envelope."""

        rows = tuple(
            {
                "row": index,
                **{name: values[index] for name, values in self.components.items()},
                "total_cost": self.per_trade_costs[index],
            }
            for index in range(self.trade_count)
        )
        return AnalysisResult(
            metadata=ResultMetadata(
                method=f"costs.{self.model_name}",
                method_version=self.model_version,
                parameters={
                    "currency": self.currency,
                    "unit": self.unit.value,
                    "assumptions": self.assumptions,
                },
                input_fingerprint=self.input_fingerprint,
            ),
            metrics={
                "trade_count": self.trade_count,
                "known_rows": self.trade_count - self.unknown_rows,
                "unknown_rows": self.unknown_rows,
                "known_total_cost": self.known_total_cost,
                "total_cost": self.total_cost,
                "component_totals": cast(Mapping[str, JsonValue], self.component_totals),
                "unit": self.unit.value,
                "currency": self.currency,
            },
            findings=self.findings,
            tables={"per_trade_costs": rows},
        )


@runtime_checkable
class CostModel(Protocol):
    """Pure model protocol for path-independent trade-level cost estimates."""

    @property
    def name(self) -> str: ...

    @property
    def version(self) -> int: ...

    def required_fields(self) -> tuple[str, ...]: ...

    def estimate(self, trades: object, market: object | None = None) -> CostEstimate: ...


@dataclass(frozen=True, slots=True)
class _TradeData:
    frame: pl.DataFrame
    diagnostics: FrameDiagnostics
    signed_quantity: FloatArray
    absolute_quantity: FloatArray
    notional: FloatArray


def _normalize_trades(
    trades: object,
    *,
    columns: TradeColumns,
    quantity_convention: QuantityConvention,
    extra_fields: Sequence[str] = (),
) -> _TradeData:
    if quantity_convention not in {"signed", "absolute"}:
        raise MethodContractError("quantity_convention must be 'signed' or 'absolute'")
    required = (*columns.required(), *extra_fields)
    frame, diagnostics = eager_frame(trades, required=required)
    if frame.is_empty():
        raise DataContractError("trades must contain at least one row")
    require_no_nulls(frame, columns.required(), name="trades")
    require_time_key(frame, columns.decision_time, name="trades")
    require_time_key(frame, columns.execution_time, name="trades")
    require_identifier(frame, columns.instrument, name="trades")
    if frame.schema[columns.decision_time] != frame.schema[columns.execution_time]:
        raise DataContractError("decision_time and execution_time must use matching dtypes")
    future_decisions = int(
        frame.select((pl.col(columns.decision_time) > pl.col(columns.execution_time)).sum()).item()
    )
    if future_decisions:
        raise DataContractError(
            f"trades contains {future_decisions} rows where decision_time exceeds execution_time"
        )
    require_numeric(frame, [columns.quantity, columns.price, columns.reference_price])
    numeric = frame.select(columns.quantity, columns.price, columns.reference_price).cast(
        pl.Float64
    )
    invalid_numeric = numeric.select(
        pl.any_horizontal(
            [
                pl.col(column).is_null() | pl.col(column).is_nan() | pl.col(column).is_infinite()
                for column in numeric.columns
            ]
        ).sum()
    ).item()
    if invalid_numeric:
        raise DataContractError(
            f"trades contains {invalid_numeric} rows with null, NaN, or infinite core values"
        )
    quantity = numeric.get_column(columns.quantity).to_numpy()
    price = numeric.get_column(columns.price).to_numpy()
    reference_price = numeric.get_column(columns.reference_price).to_numpy()
    if bool((price <= 0.0).any()) or bool((reference_price <= 0.0).any()):
        raise DataContractError("trade price and reference_price must be positive")
    side_dtype = frame.schema[columns.side]
    if not (
        side_dtype == pl.String or side_dtype == pl.Categorical or isinstance(side_dtype, pl.Enum)
    ):
        raise DataContractError("trade side must contain string or categorical buy/sell values")
    sides = frame.get_column(columns.side).cast(pl.String).str.to_lowercase().to_numpy()
    invalid_sides = ~np.isin(sides, np.array(["buy", "sell"], dtype=object))
    if bool(invalid_sides.any()):
        raise DataContractError("trade side values must be 'buy' or 'sell' (case-insensitive)")
    buy = sides == "buy"
    if quantity_convention == "signed":
        invalid_sign = (buy & (quantity < 0.0)) | (~buy & (quantity > 0.0))
        if bool(invalid_sign.any()):
            raise DataContractError(
                "signed quantity must be non-negative for buys and non-positive for sells"
            )
        signed = quantity
    else:
        if bool((quantity < 0.0).any()):
            raise DataContractError("absolute quantity convention requires non-negative quantity")
        signed = np.where(buy, quantity, -quantity)
    absolute = np.abs(signed)
    return _TradeData(
        frame=frame,
        diagnostics=diagnostics.with_execution("validate_normalized_trade_contract"),
        signed_quantity=cast(FloatArray, signed),
        absolute_quantity=cast(FloatArray, absolute),
        notional=cast(FloatArray, absolute * price),
    )


def _estimate_fingerprint(
    data: _TradeData,
    *,
    model: str,
    version: int,
    parameters: Mapping[str, JsonValue],
) -> str:
    return fingerprint(
        {
            "model": model,
            "version": version,
            "parameters": parameters,
            "trades": frame_records(data.frame),
        },
        namespace="cost-estimate",
    )


def _existing_component_guard(frame: pl.DataFrame, *, component: str, allowed: bool) -> None:
    if component in frame.columns and not allowed:
        raise MethodContractError(
            f"trades already contains {component!r}; set allow_existing=True only when "
            "the new scenario is intentionally incremental"
        )


def _observed_execution_guard(
    data: _TradeData,
    *,
    columns: TradeColumns,
    allowed: bool,
    component: str,
) -> None:
    if allowed:
        return
    different = data.frame.select(
        (pl.col(columns.price) != pl.col(columns.reference_price)).sum()
    ).item()
    if different:
        raise MethodContractError(
            f"{component} may already be present in observed execution prices; set "
            "allow_on_observed_execution=True only for an intentional incremental stress"
        )


@dataclass(frozen=True, slots=True)
class CommissionModel:
    """Fixed, per-unit, and notional commission with an explicit minimum."""

    fixed_per_trade: float = 0.0
    per_unit: float = 0.0
    notional_bps: float = 0.0
    minimum: float = 0.0
    currency: str = "USD"
    columns: TradeColumns = field(default_factory=TradeColumns)
    quantity_convention: QuantityConvention = "signed"
    allow_existing: bool = False
    name: str = field(default="commission", init=False)
    version: int = field(default=1, init=False)

    def __post_init__(self) -> None:
        for name in ("fixed_per_trade", "per_unit", "notional_bps", "minimum"):
            _non_negative(float(getattr(self, name)), name=name)
        _trimmed(self.currency, name="currency")

    def required_fields(self) -> tuple[str, ...]:
        return self.columns.required()

    def estimate(self, trades: object, market: object | None = None) -> CostEstimate:
        if market is not None:
            raise MethodContractError("CommissionModel does not consume a separate market frame")
        data = _normalize_trades(
            trades, columns=self.columns, quantity_convention=self.quantity_convention
        )
        _existing_component_guard(data.frame, component=self.name, allowed=self.allow_existing)
        raw = (
            self.fixed_per_trade
            + self.per_unit * data.absolute_quantity
            + (self.notional_bps / 10_000.0) * data.notional
        )
        active = data.absolute_quantity > 0.0
        costs = np.where(active, np.maximum(raw, self.minimum), 0.0)
        assumptions: dict[str, JsonValue] = {
            "fixed_per_trade": self.fixed_per_trade,
            "per_unit": self.per_unit,
            "notional_bps": self.notional_bps,
            "minimum": self.minimum,
            "quantity_convention": self.quantity_convention,
            "columns": self.columns.to_parameters(),
            "allow_existing": self.allow_existing,
        }
        return CostEstimate(
            model_name=self.name,
            model_version=self.version,
            currency=self.currency,
            components={self.name: tuple(float(value) for value in costs)},
            assumptions=assumptions,
            input_fingerprint=_estimate_fingerprint(
                data, model=self.name, version=self.version, parameters=assumptions
            ),
        )


@dataclass(frozen=True, slots=True)
class SpreadModel:
    """Observed or assumed quoted spread charged as half- or full-spread."""

    quoted_spread_bps: float | None = None
    mode: SpreadMode = "half"
    bid: str = "bid"
    ask: str = "ask"
    currency: str = "USD"
    columns: TradeColumns = field(default_factory=TradeColumns)
    quantity_convention: QuantityConvention = "signed"
    allow_on_observed_execution: bool = False
    allow_existing: bool = False
    name: str = field(default="spread", init=False)
    version: int = field(default=1, init=False)

    def __post_init__(self) -> None:
        if self.quoted_spread_bps is not None:
            _non_negative(self.quoted_spread_bps, name="quoted_spread_bps")
        if self.mode not in {"half", "full"}:
            raise MethodContractError("mode must be 'half' or 'full'")
        _trimmed(self.bid, name="bid")
        _trimmed(self.ask, name="ask")
        if self.bid == self.ask:
            raise MethodContractError("bid and ask columns must be different")
        _trimmed(self.currency, name="currency")

    def required_fields(self) -> tuple[str, ...]:
        extra = () if self.quoted_spread_bps is not None else (self.bid, self.ask)
        return (*self.columns.required(), *extra)

    def estimate(self, trades: object, market: object | None = None) -> CostEstimate:
        if market is not None:
            raise MethodContractError("SpreadModel expects market fields joined to trades")
        extra = () if self.quoted_spread_bps is not None else (self.bid, self.ask)
        data = _normalize_trades(
            trades,
            columns=self.columns,
            quantity_convention=self.quantity_convention,
            extra_fields=extra,
        )
        _existing_component_guard(data.frame, component=self.name, allowed=self.allow_existing)
        _observed_execution_guard(
            data,
            columns=self.columns,
            allowed=self.allow_on_observed_execution,
            component=self.name,
        )
        if self.quoted_spread_bps is None:
            require_numeric(data.frame, [self.bid, self.ask])
            quotes = data.frame.select(self.bid, self.ask).cast(pl.Float64)
            invalid = quotes.select(
                pl.any_horizontal(
                    [
                        pl.col(column).is_null()
                        | pl.col(column).is_nan()
                        | pl.col(column).is_infinite()
                        for column in quotes.columns
                    ]
                ).sum()
            ).item()
            if invalid:
                raise DataContractError(
                    "observed bid/ask spread contains missing or non-finite values"
                )
            bid = quotes.get_column(self.bid).to_numpy()
            ask = quotes.get_column(self.ask).to_numpy()
            if bool((bid <= 0.0).any()) or bool((ask < bid).any()):
                raise DataContractError("observed quotes require positive bid and ask >= bid")
            reference = (
                data.frame.get_column(self.columns.reference_price).cast(pl.Float64).to_numpy()
            )
            quoted_fraction = (ask - bid) / reference
            source = "observed_bid_ask"
        else:
            quoted_fraction = np.full(data.frame.height, self.quoted_spread_bps / 10_000.0)
            source = "assumed_bps"
        charge_fraction = quoted_fraction * (0.5 if self.mode == "half" else 1.0)
        costs = data.notional * charge_fraction
        assumptions: dict[str, JsonValue] = {
            "quoted_spread_bps": self.quoted_spread_bps,
            "mode": self.mode,
            "source": source,
            "bid": self.bid if self.quoted_spread_bps is None else None,
            "ask": self.ask if self.quoted_spread_bps is None else None,
            "quantity_convention": self.quantity_convention,
            "columns": self.columns.to_parameters(),
            "allow_on_observed_execution": self.allow_on_observed_execution,
            "allow_existing": self.allow_existing,
        }
        return CostEstimate(
            model_name=self.name,
            model_version=self.version,
            currency=self.currency,
            components={self.name: tuple(float(value) for value in costs)},
            assumptions=assumptions,
            input_fingerprint=_estimate_fingerprint(
                data, model=self.name, version=self.version, parameters=assumptions
            ),
        )


@dataclass(frozen=True, slots=True)
class SlippageModel:
    """Adverse fixed-per-unit and proportional slippage magnitude."""

    fixed_per_unit: float = 0.0
    slippage_bps: float = 0.0
    currency: str = "USD"
    columns: TradeColumns = field(default_factory=TradeColumns)
    quantity_convention: QuantityConvention = "signed"
    allow_on_observed_execution: bool = False
    allow_existing: bool = False
    name: str = field(default="slippage", init=False)
    version: int = field(default=1, init=False)

    def __post_init__(self) -> None:
        _non_negative(self.fixed_per_unit, name="fixed_per_unit")
        _non_negative(self.slippage_bps, name="slippage_bps")
        _trimmed(self.currency, name="currency")

    def required_fields(self) -> tuple[str, ...]:
        return self.columns.required()

    def estimate(self, trades: object, market: object | None = None) -> CostEstimate:
        if market is not None:
            raise MethodContractError("SlippageModel does not consume a separate market frame")
        data = _normalize_trades(
            trades, columns=self.columns, quantity_convention=self.quantity_convention
        )
        _existing_component_guard(data.frame, component=self.name, allowed=self.allow_existing)
        _observed_execution_guard(
            data,
            columns=self.columns,
            allowed=self.allow_on_observed_execution,
            component=self.name,
        )
        costs = (
            self.fixed_per_unit * data.absolute_quantity
            + (self.slippage_bps / 10_000.0) * data.notional
        )
        assumptions: dict[str, JsonValue] = {
            "fixed_per_unit": self.fixed_per_unit,
            "slippage_bps": self.slippage_bps,
            "adverse_by_side": True,
            "quantity_convention": self.quantity_convention,
            "columns": self.columns.to_parameters(),
            "allow_on_observed_execution": self.allow_on_observed_execution,
            "allow_existing": self.allow_existing,
        }
        return CostEstimate(
            model_name=self.name,
            model_version=self.version,
            currency=self.currency,
            components={self.name: tuple(float(value) for value in costs)},
            assumptions=assumptions,
            input_fingerprint=_estimate_fingerprint(
                data, model=self.name, version=self.version, parameters=assumptions
            ),
        )


def _availability_mask(
    data: _TradeData,
    *,
    available_time: str | None,
    columns: TradeColumns,
    field_name: str,
) -> npt.NDArray[np.bool_]:
    if available_time is None:
        return np.ones(data.frame.height, dtype=np.bool_)
    if data.frame.schema[available_time] != data.frame.schema[columns.execution_time]:
        raise DataContractError(
            f"{field_name} available-time dtype must match execution_time dtype"
        )
    return cast(
        npt.NDArray[np.bool_],
        data.frame.select(
            (pl.col(available_time) <= pl.col(columns.execution_time))
            .fill_null(False)
            .alias("available")
        )
        .get_column("available")
        .to_numpy(),
    )


def _complete_non_negative_column(
    data: _TradeData,
    *,
    column: str,
    positive: bool = False,
) -> FloatArray:
    require_numeric(data.frame, [column])
    values = data.frame.get_column(column).cast(pl.Float64)
    invalid = values.is_null() | values.is_nan() | values.is_infinite()
    if bool(invalid.any()):
        raise DataContractError(f"{column!r} contains missing or non-finite values")
    array = values.to_numpy()
    if positive and bool((array <= 0.0).any()):
        raise DataContractError(f"{column!r} must be positive")
    if not positive and bool((array < 0.0).any()):
        raise DataContractError(f"{column!r} must be non-negative")
    return cast(FloatArray, array)


@dataclass(frozen=True, slots=True)
class VolatilitySlippageModel:
    """Slippage proportional to an explicitly sourced volatility estimate."""

    coefficient: float
    volatility: str = "volatility"
    volatility_available_time: str | None = None
    volatility_horizon: str = "execution_horizon"
    estimator: str = "user_supplied"
    currency: str = "USD"
    columns: TradeColumns = field(default_factory=TradeColumns)
    quantity_convention: QuantityConvention = "signed"
    allow_on_observed_execution: bool = False
    name: str = field(default="volatility_slippage", init=False)
    version: int = field(default=1, init=False)

    def __post_init__(self) -> None:
        _non_negative(self.coefficient, name="coefficient")
        for value, name in (
            (self.volatility, "volatility"),
            (self.volatility_horizon, "volatility_horizon"),
            (self.estimator, "estimator"),
            (self.currency, "currency"),
        ):
            _trimmed(value, name=name)
        if self.volatility_available_time is not None:
            _trimmed(self.volatility_available_time, name="volatility_available_time")

    def required_fields(self) -> tuple[str, ...]:
        availability = (
            () if self.volatility_available_time is None else (self.volatility_available_time,)
        )
        return (*self.columns.required(), self.volatility, *availability)

    def estimate(self, trades: object, market: object | None = None) -> CostEstimate:
        if market is not None:
            raise MethodContractError(
                "VolatilitySlippageModel expects market fields joined to trades"
            )
        extra = [self.volatility]
        if self.volatility_available_time is not None:
            extra.append(self.volatility_available_time)
        data = _normalize_trades(
            trades,
            columns=self.columns,
            quantity_convention=self.quantity_convention,
            extra_fields=extra,
        )
        _observed_execution_guard(
            data,
            columns=self.columns,
            allowed=self.allow_on_observed_execution,
            component=self.name,
        )
        volatility = _complete_non_negative_column(data, column=self.volatility)
        available = _availability_mask(
            data,
            available_time=self.volatility_available_time,
            columns=self.columns,
            field_name="volatility",
        )
        if not bool(available.all()):
            raise DataContractError(
                "volatility contains values unavailable by modeled execution_time"
            )
        costs = data.notional * self.coefficient * volatility
        assumptions: dict[str, JsonValue] = {
            "coefficient": self.coefficient,
            "volatility": self.volatility,
            "volatility_available_time": self.volatility_available_time,
            "volatility_horizon": self.volatility_horizon,
            "estimator": self.estimator,
            "quantity_convention": self.quantity_convention,
            "columns": self.columns.to_parameters(),
            "allow_on_observed_execution": self.allow_on_observed_execution,
        }
        return CostEstimate(
            model_name=self.name,
            model_version=self.version,
            currency=self.currency,
            components={self.name: tuple(float(value) for value in costs)},
            assumptions=assumptions,
            input_fingerprint=_estimate_fingerprint(
                data, model=self.name, version=self.version, parameters=assumptions
            ),
        )


def _impact_estimate(
    trades: object,
    *,
    name: str,
    version: int,
    coefficient: float,
    exponent: float,
    volume: str,
    volatility: str | None,
    market_available_time: str | None,
    volume_horizon: str,
    volatility_horizon: str | None,
    max_participation: float | None,
    impact_cap: float | None,
    currency: str,
    columns: TradeColumns,
    quantity_convention: QuantityConvention,
) -> CostEstimate:
    extra = [volume]
    if volatility is not None:
        extra.append(volatility)
    if market_available_time is not None:
        extra.append(market_available_time)
    data = _normalize_trades(
        trades,
        columns=columns,
        quantity_convention=quantity_convention,
        extra_fields=extra,
    )
    volume_values = _complete_non_negative_column(data, column=volume, positive=True)
    volatility_values = (
        np.ones(data.frame.height, dtype=np.float64)
        if volatility is None
        else _complete_non_negative_column(data, column=volatility)
    )
    available = _availability_mask(
        data,
        available_time=market_available_time,
        columns=columns,
        field_name="impact market data",
    )
    if not bool(available.all()):
        raise DataContractError("impact inputs contain values unavailable by execution_time")
    participation = data.absolute_quantity / volume_values
    raw_impact = coefficient * volatility_values * np.power(participation, exponent)
    impact_fraction = np.minimum(raw_impact, impact_cap) if impact_cap is not None else raw_impact
    costs = data.notional * impact_fraction
    findings: list[Finding] = []
    if max_participation is not None:
        breaches = int((participation > max_participation).sum())
        if breaches:
            findings.append(
                Finding(
                    code="COST_PARTICIPATION_LIMIT_EXCEEDED",
                    title="Participation constraint exceeded",
                    message=f"{breaches} trades exceed the declared participation limit.",
                    state=FindingState.FAIL,
                    severity=Severity.HIGH,
                    category="costs.capacity",
                    evidence={
                        "breach_rows": breaches,
                        "max_participation": max_participation,
                        "observed_max_participation": float(participation.max()),
                    },
                )
            )
    if impact_cap is not None and bool((raw_impact > impact_cap).any()):
        findings.append(
            Finding(
                code="COST_IMPACT_CAP_APPLIED",
                title="Impact cap applied",
                message="The declared scenario cap truncated modeled price impact.",
                state=FindingState.WARN,
                severity=Severity.MEDIUM,
                category="costs.impact",
                evidence={
                    "capped_rows": int((raw_impact > impact_cap).sum()),
                    "impact_cap": impact_cap,
                },
            )
        )
    assumptions: dict[str, JsonValue] = {
        "coefficient": coefficient,
        "participation_exponent": exponent,
        "volume": volume,
        "volatility": volatility,
        "market_available_time": market_available_time,
        "volume_horizon": volume_horizon,
        "volatility_horizon": volatility_horizon,
        "max_participation": max_participation,
        "impact_cap": impact_cap,
        "temporary_impact": True,
        "quantity_convention": quantity_convention,
        "columns": columns.to_parameters(),
    }
    return CostEstimate(
        model_name=name,
        model_version=version,
        currency=currency,
        components={name: tuple(float(value) for value in costs)},
        assumptions=assumptions,
        input_fingerprint=_estimate_fingerprint(
            data, model=name, version=version, parameters=assumptions
        ),
        findings=tuple(findings),
    )


@dataclass(frozen=True, slots=True)
class ParticipationImpactModel:
    """Power-law participation impact, linear by default."""

    coefficient: float
    exponent: float = 1.0
    volume: str = "volume"
    volatility: str | None = None
    market_available_time: str | None = None
    volume_horizon: str = "execution_horizon"
    volatility_horizon: str | None = None
    max_participation: float | None = None
    impact_cap: float | None = None
    currency: str = "USD"
    columns: TradeColumns = field(default_factory=TradeColumns)
    quantity_convention: QuantityConvention = "signed"
    name: str = field(default="participation_impact", init=False)
    version: int = field(default=1, init=False)

    def __post_init__(self) -> None:
        _non_negative(self.coefficient, name="coefficient")
        _positive(self.exponent, name="exponent")
        if self.max_participation is not None:
            _positive(self.max_participation, name="max_participation")
        if self.impact_cap is not None:
            _non_negative(self.impact_cap, name="impact_cap")
        for value, name in ((self.volume, "volume"), (self.volume_horizon, "volume_horizon")):
            _trimmed(value, name=name)
        if self.volatility is not None:
            _trimmed(self.volatility, name="volatility")
        if self.volatility_horizon is not None:
            _trimmed(self.volatility_horizon, name="volatility_horizon")
        if self.market_available_time is not None:
            _trimmed(self.market_available_time, name="market_available_time")
        _trimmed(self.currency, name="currency")

    def required_fields(self) -> tuple[str, ...]:
        extra = [self.volume]
        if self.volatility is not None:
            extra.append(self.volatility)
        if self.market_available_time is not None:
            extra.append(self.market_available_time)
        return (*self.columns.required(), *extra)

    def estimate(self, trades: object, market: object | None = None) -> CostEstimate:
        if market is not None:
            raise MethodContractError(
                "ParticipationImpactModel expects market fields joined to trades"
            )
        return _impact_estimate(
            trades,
            name=self.name,
            version=self.version,
            coefficient=self.coefficient,
            exponent=self.exponent,
            volume=self.volume,
            volatility=self.volatility,
            market_available_time=self.market_available_time,
            volume_horizon=self.volume_horizon,
            volatility_horizon=self.volatility_horizon,
            max_participation=self.max_participation,
            impact_cap=self.impact_cap,
            currency=self.currency,
            columns=self.columns,
            quantity_convention=self.quantity_convention,
        )


@dataclass(frozen=True, slots=True)
class SquareRootImpactModel:
    """Square-root impact scaled by volatility and participation."""

    coefficient: float
    volume: str = "adv"
    volatility: str = "volatility"
    market_available_time: str | None = None
    volume_horizon: str = "daily"
    volatility_horizon: str = "daily"
    max_participation: float | None = None
    impact_cap: float | None = None
    currency: str = "USD"
    columns: TradeColumns = field(default_factory=TradeColumns)
    quantity_convention: QuantityConvention = "signed"
    name: str = field(default="square_root_impact", init=False)
    version: int = field(default=1, init=False)

    def __post_init__(self) -> None:
        _non_negative(self.coefficient, name="coefficient")
        if self.max_participation is not None:
            _positive(self.max_participation, name="max_participation")
        if self.impact_cap is not None:
            _non_negative(self.impact_cap, name="impact_cap")
        for value, name in (
            (self.volume, "volume"),
            (self.volatility, "volatility"),
            (self.volume_horizon, "volume_horizon"),
            (self.volatility_horizon, "volatility_horizon"),
            (self.currency, "currency"),
        ):
            _trimmed(value, name=name)
        if self.market_available_time is not None:
            _trimmed(self.market_available_time, name="market_available_time")

    def required_fields(self) -> tuple[str, ...]:
        availability = () if self.market_available_time is None else (self.market_available_time,)
        return (
            *self.columns.required(),
            self.volume,
            self.volatility,
            *availability,
        )

    def estimate(self, trades: object, market: object | None = None) -> CostEstimate:
        if market is not None:
            raise MethodContractError(
                "SquareRootImpactModel expects market fields joined to trades"
            )
        return _impact_estimate(
            trades,
            name=self.name,
            version=self.version,
            coefficient=self.coefficient,
            exponent=0.5,
            volume=self.volume,
            volatility=self.volatility,
            market_available_time=self.market_available_time,
            volume_horizon=self.volume_horizon,
            volatility_horizon=self.volatility_horizon,
            max_participation=self.max_participation,
            impact_cap=self.impact_cap,
            currency=self.currency,
            columns=self.columns,
            quantity_convention=self.quantity_convention,
        )


@dataclass(frozen=True, slots=True)
class BorrowCostModel:
    """Annualized borrow charged over explicit short holding intervals."""

    borrow_rate: str = "borrow_rate"
    holding_days: str = "holding_days"
    borrow_available_time: str | None = None
    day_count: float = 365.0
    missing: MissingBorrowPolicy = "unknown"
    conservative_rate: float | None = None
    currency: str = "USD"
    columns: TradeColumns = field(default_factory=TradeColumns)
    quantity_convention: QuantityConvention = "signed"
    allow_existing: bool = False
    name: str = field(default="borrow", init=False)
    version: int = field(default=1, init=False)

    def __post_init__(self) -> None:
        for value, name in (
            (self.borrow_rate, "borrow_rate"),
            (self.holding_days, "holding_days"),
            (self.currency, "currency"),
        ):
            _trimmed(value, name=name)
        if self.borrow_available_time is not None:
            _trimmed(self.borrow_available_time, name="borrow_available_time")
        _positive(self.day_count, name="day_count")
        if self.missing not in {"raise", "unknown", "conservative"}:
            raise MethodContractError("missing must be 'raise', 'unknown', or 'conservative'")
        if self.conservative_rate is not None:
            _non_negative(self.conservative_rate, name="conservative_rate")
        if self.missing == "conservative" and self.conservative_rate is None:
            raise MethodContractError("conservative missing policy requires conservative_rate")
        if self.missing != "conservative" and self.conservative_rate is not None:
            raise MethodContractError("conservative_rate is only valid with missing='conservative'")

    def required_fields(self) -> tuple[str, ...]:
        availability = () if self.borrow_available_time is None else (self.borrow_available_time,)
        return (
            *self.columns.required(),
            self.borrow_rate,
            self.holding_days,
            *availability,
        )

    def estimate(self, trades: object, market: object | None = None) -> CostEstimate:
        if market is not None:
            raise MethodContractError("BorrowCostModel expects borrow fields joined to trades")
        extra = [self.borrow_rate, self.holding_days]
        if self.borrow_available_time is not None:
            extra.append(self.borrow_available_time)
        data = _normalize_trades(
            trades,
            columns=self.columns,
            quantity_convention=self.quantity_convention,
            extra_fields=extra,
        )
        _existing_component_guard(data.frame, component=self.name, allowed=self.allow_existing)
        require_numeric(data.frame, [self.borrow_rate, self.holding_days])
        rates = data.frame.get_column(self.borrow_rate).cast(pl.Float64).to_numpy()
        days = data.frame.get_column(self.holding_days).cast(pl.Float64).to_numpy()
        short = data.signed_quantity < 0.0
        invalid_days = (~np.isfinite(days)) | (days < 0.0)
        if bool((invalid_days & short).any()):
            raise DataContractError("short holding_days must be finite and non-negative")
        invalid_rates = (~np.isfinite(rates)) | (rates < 0.0)
        available = _availability_mask(
            data,
            available_time=self.borrow_available_time,
            columns=self.columns,
            field_name="borrow",
        )
        unknown = short & (invalid_rates | ~available)
        if bool(unknown.any()) and self.missing == "raise":
            raise DataContractError(
                "short trades contain missing, invalid, or unavailable borrow rates"
            )
        effective_rates = rates.copy()
        if self.missing == "conservative":
            effective_rates[unknown] = cast(float, self.conservative_rate)
        costs: list[float | None] = []
        for index in range(data.frame.height):
            if not short[index]:
                costs.append(0.0)
            elif unknown[index] and self.missing == "unknown":
                costs.append(None)
            else:
                costs.append(
                    float(
                        data.notional[index] * effective_rates[index] * days[index] / self.day_count
                    )
                )
        findings: list[Finding] = []
        unknown_count = int(unknown.sum())
        if unknown_count:
            conservative = self.missing == "conservative"
            findings.append(
                Finding(
                    code=(
                        "COST_BORROW_CONSERVATIVE_ASSUMPTION"
                        if conservative
                        else "COST_BORROW_UNKNOWN"
                    ),
                    title=(
                        "Conservative borrow assumption applied"
                        if conservative
                        else "Borrow cost is unknown"
                    ),
                    message=(
                        f"{unknown_count} short trades use the declared conservative rate."
                        if conservative
                        else (
                            f"{unknown_count} short trades lack usable point-in-time "
                            "borrow evidence."
                        )
                    ),
                    state=FindingState.WARN if conservative else FindingState.UNKNOWN,
                    severity=Severity.HIGH,
                    category="costs.borrow",
                    evidence={
                        "affected_rows": unknown_count,
                        "missing_policy": self.missing,
                        "conservative_rate": self.conservative_rate,
                    },
                )
            )
        assumptions: dict[str, JsonValue] = {
            "borrow_rate": self.borrow_rate,
            "holding_days": self.holding_days,
            "borrow_available_time": self.borrow_available_time,
            "day_count": self.day_count,
            "missing": self.missing,
            "conservative_rate": self.conservative_rate,
            "annualized_rate_decimal": True,
            "quantity_convention": self.quantity_convention,
            "columns": self.columns.to_parameters(),
            "allow_existing": self.allow_existing,
        }
        return CostEstimate(
            model_name=self.name,
            model_version=self.version,
            currency=self.currency,
            components={self.name: tuple(costs)},
            assumptions=assumptions,
            input_fingerprint=_estimate_fingerprint(
                data, model=self.name, version=self.version, parameters=assumptions
            ),
            findings=tuple(findings),
        )


@dataclass(frozen=True, slots=True)
class CompositeCostModel:
    """Validated additive composition that preserves named components."""

    models: tuple[CostModel, ...]
    name: str = "composite"
    version: int = 1

    def __post_init__(self) -> None:
        _trimmed(self.name, name="name")
        if self.version < 1:
            raise MethodContractError("version must be positive")
        object.__setattr__(self, "models", tuple(self.models))
        if not self.models:
            raise MethodContractError("composite model requires at least one model")
        for model in self.models:
            if not isinstance(model, CostModel):
                raise MethodContractError("models must implement the CostModel protocol")
        names = [model.name for model in self.models]
        if len(names) != len(set(names)):
            raise MethodContractError("composite model component names must be unique")

    def required_fields(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                field_name for model in self.models for field_name in model.required_fields()
            )
        )

    def estimate(self, trades: object, market: object | None = None) -> CostEstimate:
        estimates = [model.estimate(trades, market) for model in self.models]
        currencies = {estimate.currency for estimate in estimates}
        if len(currencies) != 1:
            raise MethodContractError(
                "composite models require one currency; conversion is never implicit"
            )
        row_counts = {estimate.trade_count for estimate in estimates}
        if len(row_counts) != 1:
            raise DataContractError("composed estimates do not align to the same trade rows")
        components: dict[str, tuple[float | None, ...]] = {}
        findings: list[Finding] = []
        for estimate in estimates:
            overlap = set(components).intersection(estimate.components)
            if overlap:
                raise MethodContractError(
                    f"duplicate composed components: {', '.join(sorted(overlap))}"
                )
            components.update(estimate.components)
            findings.extend(estimate.findings)
        assumptions: dict[str, JsonValue] = {
            "components": tuple(
                {
                    "name": estimate.model_name,
                    "version": estimate.model_version,
                    "assumptions": estimate.assumptions,
                    "input_fingerprint": estimate.input_fingerprint,
                }
                for estimate in estimates
            )
        }
        return CostEstimate(
            model_name=self.name,
            model_version=self.version,
            currency=next(iter(currencies)),
            components=components,
            assumptions=assumptions,
            input_fingerprint=fingerprint(
                {
                    "model": self.name,
                    "version": self.version,
                    "components": tuple(estimate.input_fingerprint for estimate in estimates),
                },
                namespace="composite-cost-estimate",
            ),
            findings=tuple(findings),
        )


@dataclass(frozen=True, slots=True)
class CostScenario:
    """One deterministic, potentially correlated linear-cost scenario."""

    name: str
    spread_bps: float = 0.0
    slippage_bps: float = 0.0
    commission_bps: float = 0.0

    def __post_init__(self) -> None:
        _trimmed(self.name, name="scenario name")
        _non_negative(self.spread_bps, name="spread_bps")
        _non_negative(self.slippage_bps, name="slippage_bps")
        _non_negative(self.commission_bps, name="commission_bps")

    def to_parameters(self) -> dict[str, JsonValue]:
        return {
            "name": self.name,
            "spread_bps": self.spread_bps,
            "slippage_bps": self.slippage_bps,
            "commission_bps": self.commission_bps,
        }


@dataclass(frozen=True, slots=True)
class CapacityScenario:
    """Declared nonlinear impact and linear-friction assumptions."""

    name: str
    impact_coefficient: float
    spread_bps: float = 0.0
    slippage_bps: float = 0.0

    def __post_init__(self) -> None:
        _trimmed(self.name, name="scenario name")
        _non_negative(self.impact_coefficient, name="impact_coefficient")
        _non_negative(self.spread_bps, name="spread_bps")
        _non_negative(self.slippage_bps, name="slippage_bps")

    def to_parameters(self) -> dict[str, JsonValue]:
        return {
            "name": self.name,
            "impact_coefficient": self.impact_coefficient,
            "spread_bps": self.spread_bps,
            "slippage_bps": self.slippage_bps,
        }


def _finite_grid(values: Sequence[float], *, name: str) -> tuple[float, ...]:
    resolved = tuple(float(value) for value in values)
    if not resolved:
        raise MethodContractError(f"{name} must contain at least one value")
    for value in resolved:
        _non_negative(value, name=name)
    if len(resolved) != len(set(resolved)):
        raise MethodContractError(f"{name} must not contain duplicate values")
    return resolved


def _gross_pnl(data: _TradeData, *, column: str) -> FloatArray:
    _trimmed(column, name="gross_pnl")
    if column not in data.frame.columns:
        raise DataContractError(f"trades is missing required columns: {column}")
    return _complete_non_negative_or_signed_column(data.frame, column=column)


def _complete_non_negative_or_signed_column(frame: pl.DataFrame, *, column: str) -> FloatArray:
    require_numeric(frame, [column])
    values = frame.get_column(column).cast(pl.Float64)
    invalid = values.is_null() | values.is_nan() | values.is_infinite()
    if bool(invalid.any()):
        raise DataContractError(f"{column!r} contains missing or non-finite values")
    return cast(FloatArray, values.to_numpy())


def _period_values(
    frame: pl.DataFrame,
    *,
    period: str,
    values: FloatArray,
) -> FloatArray:
    if period not in frame.columns:
        raise DataContractError(f"trades is missing period column {period!r}")
    grouped = (
        frame.select(period)
        .with_columns(pl.Series("__value", values))
        .group_by(period, maintain_order=True)
        .agg(pl.col("__value").sum())
        .get_column("__value")
        .to_numpy()
    )
    return cast(FloatArray, grouped)


def _sharpe(values: FloatArray, *, annualization: float | None) -> float | None:
    if annualization is None or values.size < 2:
        return None
    standard_deviation = float(np.std(values, ddof=1))
    if standard_deviation == 0.0:
        return None
    return float(np.mean(values) / standard_deviation * math.sqrt(annualization))


def stress(
    trades: object,
    *,
    gross_pnl: str = "gross_pnl",
    spread_bps: Sequence[float] = (0.0, 2.0, 5.0, 10.0, 20.0),
    slippage_bps: Sequence[float] = (0.0, 2.0, 5.0, 10.0),
    commission_bps: Sequence[float] = (0.0,),
    scenarios: Sequence[CostScenario] | None = None,
    base_models: Sequence[CostModel] = (),
    capital: float | None = None,
    period: str = "execution_time",
    annualization: float | None = None,
    currency: str = "USD",
    columns: TradeColumns | None = None,
    quantity_convention: QuantityConvention = "signed",
    allow_on_observed_execution: bool = False,
) -> AnalysisResult:
    """Evaluate deterministic linear-cost grids or explicit correlated scenarios."""

    resolved_columns = columns or TradeColumns()
    data = _normalize_trades(
        trades, columns=resolved_columns, quantity_convention=quantity_convention
    )
    pnl = _gross_pnl(data, column=gross_pnl)
    _trimmed(period, name="period")
    _trimmed(currency, name="currency")
    if capital is not None:
        _positive(capital, name="capital")
    if annualization is not None:
        _positive(annualization, name="annualization")
    base = tuple(base_models)
    for model in base:
        if not isinstance(model, CostModel):
            raise MethodContractError("base_models must implement the CostModel protocol")
    if scenarios is None:
        spread_values = _finite_grid(spread_bps, name="spread_bps")
        slippage_values = _finite_grid(slippage_bps, name="slippage_bps")
        commission_values = _finite_grid(commission_bps, name="commission_bps")
        resolved_scenarios = tuple(
            CostScenario(
                name=f"spread={spread:g};slippage={slippage:g};commission={commission:g}",
                spread_bps=spread,
                slippage_bps=slippage,
                commission_bps=commission,
            )
            for spread, slippage, commission in itertools.product(
                spread_values, slippage_values, commission_values
            )
        )
        scenario_source = "cartesian_grid"
    else:
        if (
            tuple(spread_bps) != (0.0, 2.0, 5.0, 10.0, 20.0)
            or tuple(slippage_bps) != (0.0, 2.0, 5.0, 10.0)
            or tuple(commission_bps) != (0.0,)
        ):
            raise MethodContractError("grid parameters cannot be combined with explicit scenarios")
        resolved_scenarios = tuple(scenarios)
        if not resolved_scenarios:
            raise MethodContractError("scenarios must contain at least one CostScenario")
        if any(not isinstance(scenario, CostScenario) for scenario in resolved_scenarios):
            raise MethodContractError("scenarios must contain CostScenario values")
        scenario_source = "explicit_correlated_scenarios"
    names = [scenario.name for scenario in resolved_scenarios]
    if len(names) != len(set(names)):
        raise MethodContractError("scenario names must be unique")

    gross_total = float(pnl.sum())
    total_notional = float(data.notional.sum())
    rows: list[dict[str, JsonValue]] = []
    findings: list[Finding] = []
    for component in ("commission", "spread", "slippage"):
        _existing_component_guard(data.frame, component=component, allowed=False)
    _observed_execution_guard(
        data,
        columns=resolved_columns,
        allowed=allow_on_observed_execution,
        component="spread or slippage",
    )
    base_components: dict[str, tuple[float | None, ...]] = {}
    base_fingerprints: list[str] = []
    for model in base:
        estimate = model.estimate(data.frame)
        if estimate.currency != currency:
            raise MethodContractError("base model currency must match the stress surface currency")
        if estimate.trade_count != data.frame.height:
            raise DataContractError("base model estimate does not align to the trade rows")
        overlap = set(base_components).intersection(estimate.components)
        overlap.update({"commission", "spread", "slippage"}.intersection(estimate.components))
        if overlap:
            raise MethodContractError(
                f"stress surface contains duplicate components: {', '.join(sorted(overlap))}"
            )
        base_components.update(estimate.components)
        base_fingerprints.append(estimate.input_fingerprint)
        findings.extend(estimate.findings)
    for scenario in resolved_scenarios:
        components: dict[str, tuple[float | None, ...]] = {
            "commission": tuple(
                float(value) for value in data.notional * (scenario.commission_bps / 10_000.0)
            ),
            "spread": tuple(
                float(value) for value in data.notional * (scenario.spread_bps / 20_000.0)
            ),
            "slippage": tuple(
                float(value) for value in data.notional * (scenario.slippage_bps / 10_000.0)
            ),
            **base_components,
        }
        per_trade_costs: list[float | None] = []
        for index in range(data.frame.height):
            values = [component[index] for component in components.values()]
            per_trade_costs.append(
                None
                if any(value is None for value in values)
                else float(sum(cast(float, value) for value in values))
            )
        unknown_rows = sum(value is None for value in per_trade_costs)
        known_total_cost = float(sum(value for value in per_trade_costs if value is not None))
        total_cost = None if unknown_rows else known_total_cost
        component_totals: dict[str, JsonValue] = {
            name: (
                None
                if any(value is None for value in values)
                else float(sum(cast(float, value) for value in values))
            )
            for name, values in components.items()
        }
        if total_cost is None:
            net_pnl: float | None = None
            net_return: float | None = None
            net_sharpe: float | None = None
            status = "unknown_cost"
        else:
            net_values = pnl - np.asarray(per_trade_costs, dtype=np.float64)
            net_pnl = gross_total - total_cost
            net_return = None if capital is None else net_pnl / capital
            net_sharpe = _sharpe(
                _period_values(data.frame, period=period, values=net_values),
                annualization=annualization,
            )
            status = "ok"
        rows.append(
            {
                "scenario": scenario.name,
                "spread_bps": scenario.spread_bps,
                "slippage_bps": scenario.slippage_bps,
                "commission_bps": scenario.commission_bps,
                "gross_pnl": gross_total,
                "component_costs": component_totals,
                "known_total_cost": known_total_cost,
                "total_cost": total_cost,
                "net_pnl": net_pnl,
                "net_return": net_return,
                "net_sharpe": net_sharpe,
                "turnover": None if capital is None else total_notional / capital,
                "trade_count": data.frame.height,
                "known_cost_rows": data.frame.height - unknown_rows,
                "status": status,
            }
        )
    known_net = [cast(float, row["net_pnl"]) for row in rows if row["net_pnl"] is not None]
    if len(known_net) != len(rows):
        findings.append(
            Finding(
                code="COST_STRESS_INCOMPLETE",
                title="Stress surface contains unknown costs",
                message="At least one scenario cannot produce complete net performance.",
                state=FindingState.UNKNOWN,
                severity=Severity.HIGH,
                category="costs.stress",
                evidence={"unknown_scenarios": len(rows) - len(known_net)},
            )
        )
    return AnalysisResult(
        metadata=ResultMetadata(
            method="costs.stress",
            method_version=1,
            parameters={
                "gross_pnl": gross_pnl,
                "scenario_source": scenario_source,
                "scenarios": tuple(scenario.to_parameters() for scenario in resolved_scenarios),
                "base_models": tuple(
                    {"name": model.name, "version": model.version} for model in base
                ),
                "capital": capital,
                "period": period,
                "annualization": annualization,
                "currency": currency,
                "quantity_convention": quantity_convention,
                "columns": resolved_columns.to_parameters(),
                "allow_on_observed_execution": allow_on_observed_execution,
                "frame": data.diagnostics.to_parameters(),
            },
            input_fingerprint=fingerprint(
                {
                    "trades": frame_records(data.frame),
                    "gross_pnl": gross_pnl,
                    "scenarios": tuple(scenario.to_parameters() for scenario in resolved_scenarios),
                    "base_estimates": tuple(base_fingerprints),
                },
                namespace="cost-stress",
            ),
        ),
        metrics={
            "scenario_count": len(rows),
            "gross_pnl": gross_total,
            "total_notional": total_notional,
            "best_net_pnl": max(known_net) if known_net else None,
            "worst_net_pnl": min(known_net) if known_net else None,
            "complete_scenarios": len(known_net),
            "currency": currency,
        },
        findings=tuple(findings),
        tables={"stress_surface": tuple(rows)},
        warnings=(
            "Quoted spread_bps is a full bid/ask spread; the stress surface charges half-spread.",
            "Scenario results are path-independent estimates, not simulated executions.",
        ),
    )


def _metric_at_cost(
    *,
    data: _TradeData,
    gross_pnl: FloatArray,
    cost_bps: float,
    metric: BreakEvenMetric,
    threshold: float,
    period: str,
    annualization: float | None,
    capital: float | None,
) -> tuple[float, float]:
    del threshold
    costs = data.notional * (cost_bps / 10_000.0)
    net = gross_pnl - costs
    net_total = float(net.sum())
    if metric == "net_pnl":
        return net_total, float(costs.sum())
    if capital is None:
        raise MethodContractError(f"metric={metric!r} requires capital")
    if metric == "net_return":
        return net_total / capital, float(costs.sum())
    periods = _period_values(data.frame, period=period, values=net)
    if annualization is None:
        raise MethodContractError(f"metric={metric!r} requires annualization")
    if metric == "net_sharpe":
        observed = _sharpe(periods / capital, annualization=annualization)
        if observed is None:
            raise DataContractError("net Sharpe is undefined for this sample")
        return observed, float(costs.sum())
    returns = periods / capital
    if bool((returns <= -1.0).any()):
        raise DataContractError("CAGR is undefined when a modeled period return is <= -100%")
    growth = float(np.prod(1.0 + returns))
    return growth ** (annualization / periods.size) - 1.0, float(costs.sum())


def break_even_cost(
    trades: object,
    *,
    gross_pnl: str = "gross_pnl",
    metric: BreakEvenMetric = "net_pnl",
    threshold: float = 0.0,
    lower_bps: float = 0.0,
    upper_bps: float = 1_000.0,
    tolerance_bps: float = 1e-6,
    max_iterations: int = 100,
    capital: float | None = None,
    period: str = "execution_time",
    annualization: float | None = None,
    columns: TradeColumns | None = None,
    quantity_convention: QuantityConvention = "signed",
) -> AnalysisResult:
    """Bracket and bisect the all-in bps where a declared metric crosses a threshold."""

    if metric not in {"net_pnl", "net_return", "net_sharpe", "cagr"}:
        raise MethodContractError("metric must be net_pnl, net_return, net_sharpe, or cagr")
    if not math.isfinite(threshold):
        raise MethodContractError("threshold must be finite")
    _non_negative(lower_bps, name="lower_bps")
    _positive(upper_bps, name="upper_bps")
    if lower_bps >= upper_bps:
        raise MethodContractError("lower_bps must be below upper_bps")
    _positive(tolerance_bps, name="tolerance_bps")
    if tolerance_bps >= upper_bps - lower_bps:
        raise MethodContractError("tolerance_bps must be smaller than the search interval")
    if max_iterations < 1:
        raise MethodContractError("max_iterations must be positive")
    if capital is not None:
        _positive(capital, name="capital")
    if annualization is not None:
        _positive(annualization, name="annualization")
    resolved_columns = columns or TradeColumns()
    data = _normalize_trades(
        trades, columns=resolved_columns, quantity_convention=quantity_convention
    )
    pnl = _gross_pnl(data, column=gross_pnl)

    check_points = np.linspace(lower_bps, upper_bps, num=33)
    checked: list[tuple[float, float, float]] = []
    for point in check_points:
        value, total_cost = _metric_at_cost(
            data=data,
            gross_pnl=pnl,
            cost_bps=float(point),
            metric=metric,
            threshold=threshold,
            period=period,
            annualization=annualization,
            capital=capital,
        )
        checked.append((float(point), value, total_cost))
    monotonic = all(right[1] <= left[1] + 1e-12 for left, right in itertools.pairwise(checked))
    findings: list[Finding] = []
    trace: list[dict[str, JsonValue]] = [
        {"cost_bps": point, "metric_value": value, "total_cost": total_cost}
        for point, value, total_cost in checked
    ]
    solution: float | None = None
    iterations = 0
    if not monotonic:
        status = "non_monotonic"
        findings.append(
            Finding(
                code="COST_BREAK_EVEN_NON_MONOTONIC",
                title="Break-even target is not monotonic",
                message="The declared metric is not decreasing over the search domain.",
                state=FindingState.UNKNOWN,
                severity=Severity.HIGH,
                category="costs.break_even",
                evidence={"checked_points": len(checked)},
            )
        )
    elif checked[0][1] <= threshold:
        solution = lower_bps
        status = "crossed_at_lower_bound"
    elif checked[-1][1] > threshold:
        status = "no_crossing"
        findings.append(
            Finding(
                code="COST_BREAK_EVEN_NOT_BRACKETED",
                title="Break-even is outside the declared domain",
                message="The target did not cross the threshold within the supplied bounds.",
                state=FindingState.UNKNOWN,
                severity=Severity.MEDIUM,
                category="costs.break_even",
                evidence={"lower_bps": lower_bps, "upper_bps": upper_bps},
            )
        )
    else:
        low = lower_bps
        high = upper_bps
        while high - low > tolerance_bps and iterations < max_iterations:
            midpoint = (low + high) / 2.0
            value, total_cost = _metric_at_cost(
                data=data,
                gross_pnl=pnl,
                cost_bps=midpoint,
                metric=metric,
                threshold=threshold,
                period=period,
                annualization=annualization,
                capital=capital,
            )
            trace.append({"cost_bps": midpoint, "metric_value": value, "total_cost": total_cost})
            if value > threshold:
                low = midpoint
            else:
                high = midpoint
            iterations += 1
        solution = (low + high) / 2.0
        status = "converged" if high - low <= tolerance_bps else "iteration_limit"
        if status == "iteration_limit":
            findings.append(
                Finding(
                    code="COST_BREAK_EVEN_ITERATION_LIMIT",
                    title="Break-even tolerance was not reached",
                    message="Bisection stopped at the declared maximum iteration count.",
                    state=FindingState.WARN,
                    severity=Severity.MEDIUM,
                    category="costs.break_even",
                    evidence={"remaining_width_bps": high - low},
                )
            )
    return AnalysisResult(
        metadata=ResultMetadata(
            method="costs.break_even_cost",
            method_version=1,
            parameters={
                "gross_pnl": gross_pnl,
                "metric": metric,
                "threshold": threshold,
                "lower_bps": lower_bps,
                "upper_bps": upper_bps,
                "tolerance_bps": tolerance_bps,
                "max_iterations": max_iterations,
                "capital": capital,
                "period": period,
                "annualization": annualization,
                "quantity_convention": quantity_convention,
                "columns": resolved_columns.to_parameters(),
                "frame": data.diagnostics.to_parameters(),
            },
            input_fingerprint=fingerprint(
                {"trades": frame_records(data.frame), "gross_pnl": gross_pnl},
                namespace="cost-break-even",
            ),
        ),
        metrics={
            "status": status,
            "metric": metric,
            "threshold": threshold,
            "solution_bps": solution,
            "monotonic_decreasing": monotonic,
            "iterations": iterations,
            "lower_bps": lower_bps,
            "upper_bps": upper_bps,
            "tolerance_bps": tolerance_bps,
        },
        findings=tuple(findings),
        tables={"solver_trace": tuple(trace)},
        warnings=(
            "The solution is valid only inside the declared bracket; no extrapolation is used.",
        ),
    )


def liquidity_diagnostics(
    trades: object,
    *,
    volume: str = "adv",
    available_time: str | None = None,
    classification_mode: LiquidityMode,
    max_participation: float = 0.1,
    volume_horizon: str = "daily",
    estimation_lag: str = "user_declared",
    columns: TradeColumns | None = None,
    quantity_convention: QuantityConvention = "signed",
) -> AnalysisResult:
    """Measure participation coverage and constraints without fabricating missing liquidity."""

    resolved_columns = columns or TradeColumns()
    extra = [volume]
    if available_time is not None:
        extra.append(available_time)
    data = _normalize_trades(
        trades,
        columns=resolved_columns,
        quantity_convention=quantity_convention,
        extra_fields=extra,
    )
    if classification_mode not in {"point_in_time", "retrospective"}:
        raise MethodContractError("classification_mode must be 'point_in_time' or 'retrospective'")
    if classification_mode == "point_in_time" and available_time is None:
        raise MethodContractError(
            "point_in_time liquidity analysis requires available_time evidence"
        )
    _positive(max_participation, name="max_participation")
    _trimmed(volume_horizon, name="volume_horizon")
    _trimmed(estimation_lag, name="estimation_lag")
    require_numeric(data.frame, [volume])
    volumes = data.frame.get_column(volume).cast(pl.Float64).to_numpy()
    valid = np.isfinite(volumes) & (volumes > 0.0)
    available = _availability_mask(
        data,
        available_time=available_time,
        columns=resolved_columns,
        field_name="liquidity",
    )
    known = valid & available
    participation: FloatArray = np.full(data.frame.height, np.nan, dtype=np.float64)
    participation[known] = data.absolute_quantity[known] / volumes[known]
    breached = known & (participation > max_participation)
    status = np.where(~known, "unknown", np.where(breached, "breach", "pass"))
    evidence = data.frame.select(
        resolved_columns.execution_time,
        resolved_columns.instrument,
        resolved_columns.quantity,
        volume,
        *(() if available_time is None else (available_time,)),
    ).with_columns(
        pl.Series(
            "participation",
            [
                None if not known[index] else float(participation[index])
                for index in range(data.frame.height)
            ],
        ),
        pl.Series("status", status),
    )
    findings: list[Finding] = []
    unknown_count = int((~known).sum())
    breach_count = int(breached.sum())
    if unknown_count:
        findings.append(
            Finding(
                code="COST_LIQUIDITY_UNKNOWN",
                title="Liquidity evidence is incomplete",
                message=f"{unknown_count} trades have missing, invalid, or unavailable volume.",
                state=FindingState.UNKNOWN,
                severity=Severity.HIGH,
                category="costs.liquidity",
                evidence={"unknown_rows": unknown_count},
            )
        )
    if breach_count:
        findings.append(
            Finding(
                code="COST_LIQUIDITY_CONSTRAINT_BREACH",
                title="Participation constraint breached",
                message=f"{breach_count} trades exceed the declared participation limit.",
                state=FindingState.FAIL,
                severity=Severity.HIGH,
                category="costs.liquidity",
                evidence={
                    "breach_rows": breach_count,
                    "max_participation": max_participation,
                },
            )
        )
    if classification_mode == "retrospective":
        findings.append(
            Finding(
                code="COST_LIQUIDITY_RETROSPECTIVE",
                title="Liquidity evidence is retrospective",
                message=(
                    "The analysis does not claim the volume estimate was available at execution."
                ),
                state=FindingState.WARN,
                severity=Severity.MEDIUM,
                category="costs.temporal",
            )
        )
    known_values = participation[known]
    return AnalysisResult(
        metadata=ResultMetadata(
            method="costs.liquidity_diagnostics",
            method_version=1,
            parameters={
                "volume": volume,
                "available_time": available_time,
                "classification_mode": classification_mode,
                "max_participation": max_participation,
                "volume_horizon": volume_horizon,
                "estimation_lag": estimation_lag,
                "quantity_convention": quantity_convention,
                "columns": resolved_columns.to_parameters(),
                "frame": data.diagnostics.to_parameters(),
            },
            input_fingerprint=fingerprint(
                {"trades": frame_records(data.frame), "volume": volume},
                namespace="liquidity-diagnostics",
            ),
        ),
        metrics={
            "trade_count": data.frame.height,
            "known_rows": int(known.sum()),
            "unknown_rows": unknown_count,
            "coverage": float(known.mean()),
            "breach_rows": breach_count,
            "breach_fraction": float(breached.mean()),
            "median_participation": (float(np.median(known_values)) if known_values.size else None),
            "p95_participation": (
                float(np.quantile(known_values, 0.95)) if known_values.size else None
            ),
            "max_observed_participation": (
                float(known_values.max()) if known_values.size else None
            ),
        },
        findings=tuple(findings),
        tables={"liquidity": frame_records(evidence)},
    )


def capacity_curve(
    trades: object,
    *,
    capital: Sequence[float],
    base_capital: float,
    scenarios: Sequence[CapacityScenario],
    gross_pnl: str = "gross_pnl",
    volume: str = "adv",
    volatility: str = "volatility",
    available_time: str | None = None,
    classification_mode: LiquidityMode,
    max_participation: float = 0.1,
    volume_horizon: str = "daily",
    volatility_horizon: str = "daily",
    estimation_lag: str = "user_declared",
    period: str = "execution_time",
    annualization: float | None = None,
    columns: TradeColumns | None = None,
    quantity_convention: QuantityConvention = "signed",
) -> AnalysisResult:
    """Return scenario capacity curves over capital with explicit unknown liquidity."""

    resolved_columns = columns or TradeColumns()
    extra = [gross_pnl, volume, volatility]
    if available_time is not None:
        extra.append(available_time)
    data = _normalize_trades(
        trades,
        columns=resolved_columns,
        quantity_convention=quantity_convention,
        extra_fields=extra,
    )
    if classification_mode not in {"point_in_time", "retrospective"}:
        raise MethodContractError("classification_mode must be 'point_in_time' or 'retrospective'")
    if classification_mode == "point_in_time" and available_time is None:
        raise MethodContractError(
            "point_in_time capacity analysis requires available_time evidence"
        )
    base_capital = _positive(base_capital, name="base_capital")
    capital_values = tuple(float(value) for value in capital)
    if not capital_values:
        raise MethodContractError("capital must contain at least one value")
    for capital_point in capital_values:
        _positive(capital_point, name="capital")
    if len(capital_values) != len(set(capital_values)):
        raise MethodContractError("capital must not contain duplicate values")
    if tuple(sorted(capital_values)) != capital_values:
        raise MethodContractError("capital must be strictly increasing")
    resolved_scenarios = tuple(scenarios)
    if not resolved_scenarios:
        raise MethodContractError("scenarios must contain at least one CapacityScenario")
    if any(not isinstance(scenario, CapacityScenario) for scenario in resolved_scenarios):
        raise MethodContractError("scenarios must contain CapacityScenario values")
    names = [scenario.name for scenario in resolved_scenarios]
    if len(names) != len(set(names)):
        raise MethodContractError("capacity scenario names must be unique")
    _positive(max_participation, name="max_participation")
    for label_value, name in (
        (volume_horizon, "volume_horizon"),
        (volatility_horizon, "volatility_horizon"),
        (estimation_lag, "estimation_lag"),
        (period, "period"),
    ):
        _trimmed(label_value, name=name)
    if annualization is not None:
        _positive(annualization, name="annualization")
    base_pnl = _gross_pnl(data, column=gross_pnl)
    require_numeric(data.frame, [volume, volatility])
    volumes = data.frame.get_column(volume).cast(pl.Float64).to_numpy()
    volatilities = data.frame.get_column(volatility).cast(pl.Float64).to_numpy()
    valid_market = (
        np.isfinite(volumes) & (volumes > 0.0) & np.isfinite(volatilities) & (volatilities >= 0.0)
    )
    available = _availability_mask(
        data,
        available_time=available_time,
        columns=resolved_columns,
        field_name="capacity market data",
    )
    known = valid_market & available
    cost_known = known | (data.absolute_quantity == 0.0)
    coverage = float(known.mean())
    rows: list[dict[str, JsonValue]] = []
    any_breach = False
    for scenario in resolved_scenarios:
        for capital_value in capital_values:
            scale = capital_value / base_capital
            quantity = data.absolute_quantity * scale
            notional = data.notional * scale
            participation: FloatArray = np.full(data.frame.height, np.nan, dtype=np.float64)
            participation[known] = quantity[known] / volumes[known]
            participation[(data.absolute_quantity == 0.0) & ~known] = 0.0
            breached = known & (participation > max_participation)
            any_breach = any_breach or bool(breached.any())
            impact_fraction: FloatArray = np.full(data.frame.height, np.nan, dtype=np.float64)
            impact_fraction[known] = (
                scenario.impact_coefficient * volatilities[known] * np.sqrt(participation[known])
            )
            impact_fraction[(data.absolute_quantity == 0.0) & ~known] = 0.0
            known_impact_cost = float(np.sum(notional[cost_known] * impact_fraction[cost_known]))
            spread_cost = float(notional.sum() * scenario.spread_bps / 20_000.0)
            slippage_cost = float(notional.sum() * scenario.slippage_bps / 10_000.0)
            gross_total = float(base_pnl.sum() * scale)
            incomplete = not bool(cost_known.all())
            total_cost = None if incomplete else known_impact_cost + spread_cost + slippage_cost
            if total_cost is None:
                net_pnl: float | None = None
                net_return: float | None = None
                net_sharpe: float | None = None
                status = "unknown_liquidity"
            else:
                per_trade_cost = (
                    notional * scenario.spread_bps / 20_000.0
                    + notional * scenario.slippage_bps / 10_000.0
                    + notional * impact_fraction
                )
                net_values = base_pnl * scale - per_trade_cost
                net_pnl = gross_total - total_cost
                net_return = net_pnl / capital_value
                net_sharpe = _sharpe(
                    _period_values(data.frame, period=period, values=net_values),
                    annualization=annualization,
                )
                status = "constraint_breach" if bool(breached.any()) else "ok"
            known_participation = participation[known]
            rows.append(
                {
                    "scenario": scenario.name,
                    "capital": capital_value,
                    "scale": scale,
                    "gross_pnl": gross_total,
                    "gross_turnover": float(notional.sum() / capital_value),
                    "liquidity_coverage": coverage,
                    "median_participation": (
                        float(np.median(known_participation)) if known_participation.size else None
                    ),
                    "max_observed_participation": (
                        float(known_participation.max()) if known_participation.size else None
                    ),
                    "participation_breach_rows": int(breached.sum()),
                    "known_impact_cost": known_impact_cost,
                    "impact_cost": None if incomplete else known_impact_cost,
                    "spread_cost": spread_cost,
                    "slippage_cost": slippage_cost,
                    "total_cost": total_cost,
                    "net_pnl": net_pnl,
                    "net_return": net_return,
                    "net_sharpe": net_sharpe,
                    "status": status,
                }
            )
    findings: list[Finding] = []
    unknown_count = int((~known).sum())
    if unknown_count:
        findings.append(
            Finding(
                code="COST_CAPACITY_UNKNOWN_LIQUIDITY",
                title="Capacity is unknown for incomplete liquidity evidence",
                message=f"{unknown_count} base trades lack usable volume or volatility evidence.",
                state=FindingState.UNKNOWN,
                severity=Severity.HIGH,
                category="costs.capacity",
                evidence={"unknown_rows": unknown_count, "coverage": coverage},
            )
        )
    if any_breach:
        findings.append(
            Finding(
                code="COST_CAPACITY_CONSTRAINT_BREACH",
                title="Capacity curve breaches participation constraints",
                message="At least one capital/scenario point exceeds the declared limit.",
                state=FindingState.FAIL,
                severity=Severity.HIGH,
                category="costs.capacity",
                evidence={"max_participation": max_participation},
            )
        )
    if classification_mode == "retrospective":
        findings.append(
            Finding(
                code="COST_CAPACITY_RETROSPECTIVE",
                title="Capacity evidence is retrospective",
                message="The curve does not claim liquidity inputs were available at execution.",
                state=FindingState.WARN,
                severity=Severity.MEDIUM,
                category="costs.temporal",
            )
        )
    return AnalysisResult(
        metadata=ResultMetadata(
            method="costs.capacity_curve",
            method_version=1,
            parameters={
                "capital": capital_values,
                "base_capital": base_capital,
                "scenarios": tuple(scenario.to_parameters() for scenario in resolved_scenarios),
                "gross_pnl": gross_pnl,
                "volume": volume,
                "volatility": volatility,
                "available_time": available_time,
                "classification_mode": classification_mode,
                "max_participation": max_participation,
                "volume_horizon": volume_horizon,
                "volatility_horizon": volatility_horizon,
                "estimation_lag": estimation_lag,
                "period": period,
                "annualization": annualization,
                "quantity_convention": quantity_convention,
                "columns": resolved_columns.to_parameters(),
                "frame": data.diagnostics.to_parameters(),
            },
            input_fingerprint=fingerprint(
                {
                    "trades": frame_records(data.frame),
                    "capital": capital_values,
                    "scenarios": tuple(scenario.to_parameters() for scenario in resolved_scenarios),
                },
                namespace="capacity-curve",
            ),
        ),
        metrics={
            "curve_points": len(rows),
            "capital_points": len(capital_values),
            "scenario_count": len(resolved_scenarios),
            "liquidity_coverage": coverage,
            "unknown_liquidity_rows": unknown_count,
            "returns_single_capacity_number": False,
        },
        findings=tuple(findings),
        tables={"capacity_curve": tuple(rows)},
        warnings=(
            "Square-root impact is a declared scenario model, not a universal market law.",
            "The result intentionally returns a curve and does not infer one capacity number.",
        ),
    )


__all__ = [
    "BorrowCostModel",
    "BreakEvenMetric",
    "CapacityScenario",
    "CommissionModel",
    "CompositeCostModel",
    "CostEstimate",
    "CostModel",
    "CostScenario",
    "CostUnit",
    "LiquidityMode",
    "MissingBorrowPolicy",
    "ParticipationImpactModel",
    "QuantityConvention",
    "SlippageModel",
    "SpreadMode",
    "SpreadModel",
    "SquareRootImpactModel",
    "TradeColumns",
    "VolatilitySlippageModel",
    "break_even_cost",
    "capacity_curve",
    "liquidity_diagnostics",
    "stress",
]
