"""Normalized empirical option-chain contracts and derived coordinates."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import TypeAlias, cast

import numpy as np
import numpy.typing as npt
import polars as pl
from lacuna.adapters import to_polars
from lacuna.exceptions import DataContractError, MethodContractError
from lacuna.types import AnalysisResult, JsonValue, ResultMetadata

FloatArray: TypeAlias = npt.NDArray[np.float64]

REQUIRED_CHAIN_COLUMNS = (
    "time",
    "instrument",
    "underlying",
    "expiration",
    "strike",
    "option_type",
    "bid",
    "ask",
    "underlying_price",
    "rate",
    "dividend",
)
OPTIONAL_CHAIN_COLUMNS = (
    "mid",
    "iv",
    "delta",
    "gamma",
    "vega",
    "theta",
    "open_interest",
    "volume",
)


@dataclass(frozen=True, slots=True)
class OptionFrameResult:
    """A normalized options frame and its immutable evidence."""

    frame: pl.DataFrame
    evidence: AnalysisResult


@dataclass(frozen=True, slots=True)
class OptionChain(OptionFrameResult):
    """A chain that passed the `lacuna-options` normalized schema."""


def _mapping(columns: Mapping[str, str] | None) -> dict[str, str]:
    resolved = {column: column for column in (*REQUIRED_CHAIN_COLUMNS, *OPTIONAL_CHAIN_COLUMNS)}
    if columns is None:
        return resolved
    if not isinstance(columns, Mapping):
        raise MethodContractError("columns must be a canonical-to-source mapping")
    if any(
        not isinstance(canonical, str) or not canonical or not isinstance(source, str) or not source
        for canonical, source in columns.items()
    ):
        raise MethodContractError("column mappings must use non-empty string names")
    unknown = sorted(set(columns).difference(resolved))
    if unknown:
        raise MethodContractError(f"unknown canonical option columns: {', '.join(unknown)}")
    resolved.update(columns)
    if len(set(resolved.values())) != len(resolved):
        raise MethodContractError("option source columns must map uniquely")
    return resolved


def _rename(frame: pl.DataFrame, columns: Mapping[str, str]) -> pl.DataFrame:
    source_columns = set(frame.columns)
    missing = sorted(
        columns[column]
        for column in REQUIRED_CHAIN_COLUMNS
        if columns[column] not in source_columns
    )
    if missing:
        raise DataContractError(f"option chain is missing required columns: {', '.join(missing)}")
    present_mapping = {
        source: canonical
        for canonical, source in columns.items()
        if source in source_columns and source != canonical
    }
    moving_sources = set(present_mapping)
    collisions = sorted(
        canonical
        for source, canonical in present_mapping.items()
        if canonical in source_columns and canonical not in moving_sources and canonical != source
    )
    if collisions:
        raise DataContractError(
            f"option normalization would overwrite existing columns: {', '.join(collisions)}"
        )
    return frame.rename(present_mapping)


def _require_numeric(frame: pl.DataFrame, columns: Sequence[str]) -> None:
    invalid_dtypes = [column for column in columns if not frame.schema[column].is_numeric()]
    if invalid_dtypes:
        details = ", ".join(f"{column}={frame.schema[column]}" for column in invalid_dtypes)
        raise DataContractError(f"option numeric columns have invalid dtypes: {details}")
    invalid_values = [
        column
        for column in columns
        if frame.get_column(column).null_count()
        or not bool(frame.select(pl.col(column).is_finite().all()).item())
    ]
    if invalid_values:
        raise DataContractError(
            f"option numeric columns contain null or non-finite values: {', '.join(invalid_values)}"
        )


def _maturity_expression(dtype: pl.DataType, year_basis: float) -> pl.Expr:
    duration = pl.col("expiration") - pl.col("time")
    if dtype == pl.Date:
        return duration.dt.total_days().cast(pl.Float64) / year_basis
    if isinstance(dtype, pl.Datetime):
        seconds_per_year = year_basis * 24.0 * 60.0 * 60.0
        return duration.dt.total_seconds().cast(pl.Float64) / seconds_per_year
    raise DataContractError("option time and expiration must be Date or Datetime columns")


def validate_chain(
    data: object,
    *,
    columns: Mapping[str, str] | None = None,
    year_basis: float = 365.25,
) -> OptionChain:
    """Validate and normalize quotes, then derive forward coordinates.

    ``forward`` uses continuously compounded carry,
    :math:`S exp((r-q)T)`. ``log_moneyness`` is :math:`log(K/F)`. The caller
    supplies rates, dividend yields, and the day-count denominator; Lacuna does
    not infer them from vendor or market conventions.
    """

    if isinstance(year_basis, bool) or not isinstance(year_basis, int | float):
        raise MethodContractError("year_basis must be a positive finite number")
    resolved_basis = float(year_basis)
    if not math.isfinite(resolved_basis) or resolved_basis <= 0.0:
        raise MethodContractError("year_basis must be a positive finite number")
    resolved_columns = _mapping(columns)
    normalized = to_polars(data, collect=True)
    if isinstance(normalized, pl.LazyFrame):  # pragma: no cover - collect=True contract
        normalized = normalized.collect()
    frame = _rename(normalized, resolved_columns)
    if frame.is_empty():
        raise DataContractError("option chain must contain at least one quote")
    if any(frame.get_column(column).null_count() for column in REQUIRED_CHAIN_COLUMNS):
        raise DataContractError("required option-chain columns must not contain nulls")
    if frame.schema["time"] != frame.schema["expiration"]:
        raise DataContractError("time and expiration must use the same physical dtype and timezone")

    numeric = ["strike", "bid", "ask", "underlying_price", "rate", "dividend"]
    numeric.extend(column for column in OPTIONAL_CHAIN_COLUMNS if column in frame.columns)
    _require_numeric(frame, numeric)
    if bool(frame.select((pl.col("expiration") <= pl.col("time")).any()).item()):
        raise DataContractError("every option expiration must be strictly after its quote time")
    invalid_option_types = sorted(
        set(frame.get_column("option_type").cast(pl.String).unique().to_list()).difference(
            {"call", "put"}
        )
    )
    if invalid_option_types:
        raise DataContractError(
            "option_type must contain only explicit 'call' or 'put' values; received "
            + ", ".join(str(item) for item in invalid_option_types)
        )
    if bool(
        frame.select(
            (
                (pl.col("strike") <= 0.0)
                | (pl.col("underlying_price") <= 0.0)
                | (pl.col("bid") < 0.0)
                | (pl.col("ask") < pl.col("bid"))
            ).any()
        ).item()
    ):
        raise DataContractError(
            "strikes and underlyings must be positive, quotes non-negative, and bid <= ask"
        )

    mid_computed = "mid" not in frame.columns
    if mid_computed:
        frame = frame.with_columns(((pl.col("bid") + pl.col("ask")) / 2.0).alias("mid"))
    elif bool(
        frame.select(
            ((pl.col("mid") < pl.col("bid")) | (pl.col("mid") > pl.col("ask"))).any()
        ).item()
    ):
        raise DataContractError("mid must lie inside the inclusive bid/ask interval")
    if "iv" in frame.columns and bool(frame.select((pl.col("iv") <= 0.0).any()).item()):
        raise DataContractError("implied volatility must be positive")
    if "delta" in frame.columns and bool(frame.select((pl.col("delta").abs() > 1.0).any()).item()):
        raise DataContractError("delta must lie in the closed interval [-1, 1]")
    non_negative_optional = [
        column for column in ("gamma", "vega", "open_interest", "volume") if column in frame.columns
    ]
    if any(
        bool(frame.select((pl.col(column) < 0.0).any()).item()) for column in non_negative_optional
    ):
        raise DataContractError("gamma, vega, open interest, and volume must be non-negative")

    maturity = _maturity_expression(frame.schema["time"], resolved_basis)
    frame = (
        frame.with_columns(maturity.alias("time_to_expiry_years"))
        .with_columns(
            (
                pl.col("underlying_price")
                * ((pl.col("rate") - pl.col("dividend")) * pl.col("time_to_expiry_years")).exp()
            ).alias("forward")
        )
        .with_columns((pl.col("strike") / pl.col("forward")).log().alias("log_moneyness"))
    )
    _require_numeric(frame, ("mid", "time_to_expiry_years", "forward", "log_moneyness"))
    if bool(frame.select((pl.col("time_to_expiry_years") <= 0.0).any()).item()):
        raise DataContractError("time to expiry must be positive under the declared year basis")
    if bool(frame.select((pl.col("forward") <= 0.0).any()).item()):
        raise DataContractError("derived forwards must be positive")

    evidence = AnalysisResult(
        metadata=ResultMetadata(
            method="options.validate_chain",
            method_version=1,
            parameters={
                "source_type": f"{type(data).__module__}.{type(data).__name__}",
                "column_mapping": cast(Mapping[str, JsonValue], resolved_columns),
                "year_basis": resolved_basis,
                "forward_convention": "S*exp((rate-dividend)*T)",
                "moneyness_convention": "log(strike/forward)",
                "option_type_values": ("call", "put"),
                "mid_computed": mid_computed,
                "materialized": True,
            },
        ),
        metrics={
            "quote_count": frame.height,
            "instrument_count": frame.get_column("instrument").n_unique(),
            "underlying_count": frame.get_column("underlying").n_unique(),
            "expiration_count": frame.get_column("expiration").n_unique(),
        },
    )
    return OptionChain(frame=frame, evidence=evidence)


def delta_buckets(
    chain: OptionChain,
    *,
    edges: Sequence[float] = (0.0, 0.10, 0.25, 0.40, 0.60, 0.75, 0.90, 1.0),
) -> OptionFrameResult:
    """Assign deterministic left-closed buckets over absolute option delta."""

    if not isinstance(chain, OptionChain):
        raise MethodContractError("chain must be the result of validate_chain")
    if "delta" not in chain.frame.columns:
        raise DataContractError("delta_buckets requires a validated delta column")
    try:
        resolved_edges: FloatArray = np.asarray(edges, dtype=np.float64)
    except (TypeError, ValueError) as error:
        raise MethodContractError("edges must be finite numeric boundaries") from error
    if (
        resolved_edges.ndim != 1
        or resolved_edges.size < 2
        or not np.isfinite(resolved_edges).all()
        or resolved_edges[0] != 0.0
        or resolved_edges[-1] != 1.0
        or bool(np.any(np.diff(resolved_edges) <= 0.0))
    ):
        raise MethodContractError(
            "edges must be strictly increasing finite boundaries starting at 0 and ending at 1"
        )
    labels = tuple(
        f"[{left:.2f},{right:.2f}{']' if index == resolved_edges.size - 2 else ')'}"
        for index, (left, right) in enumerate(pairwise(resolved_edges))
    )
    delta: FloatArray = (
        chain.frame.get_column("delta").abs().to_numpy().astype(np.float64, copy=False)
    )
    indices = np.searchsorted(resolved_edges, delta, side="right") - 1
    indices = np.minimum(indices, len(labels) - 1)
    bucket_values = np.asarray(labels, dtype=object)[indices]
    frame = chain.frame.with_columns(pl.Series("delta_bucket", bucket_values))
    counts = frame.group_by("delta_bucket").len(name="quotes").sort("delta_bucket").to_dicts()
    evidence = AnalysisResult(
        metadata=ResultMetadata(
            method="options.delta_buckets",
            method_version=1,
            parameters={
                "edges": tuple(float(value) for value in resolved_edges),
                "closure": "left_closed_right_open_except_final_closed",
                "coordinate": "absolute_delta",
            },
        ),
        metrics={"quote_count": frame.height, "occupied_buckets": len(counts)},
        tables={"bucket_counts": tuple(cast(dict[str, JsonValue], row) for row in counts)},
    )
    return OptionFrameResult(frame=frame, evidence=evidence)


def empirical_residual(
    chain: OptionChain,
    *,
    observed: str = "iv",
    expected: str = "expected_iv",
    output: str = "iv_residual",
) -> OptionFrameResult:
    """Compute observed-minus-expected volatility with grouped evidence."""

    if not isinstance(chain, OptionChain):
        raise MethodContractError("chain must be the result of validate_chain")
    if any(not isinstance(name, str) or not name for name in (observed, expected, output)):
        raise MethodContractError("residual column names must be non-empty strings")
    if output in chain.frame.columns and output not in {observed, expected}:
        raise DataContractError(f"residual output column already exists: {output!r}")
    missing = sorted({observed, expected}.difference(chain.frame.columns))
    if missing:
        raise DataContractError(f"residual inputs are missing: {', '.join(missing)}")
    _require_numeric(chain.frame, (observed, expected))
    if bool(
        chain.frame.select(((pl.col(observed) <= 0.0) | (pl.col(expected) <= 0.0)).any()).item()
    ):
        raise DataContractError("observed and expected volatility must be positive")
    frame = chain.frame.with_columns((pl.col(observed) - pl.col(expected)).alias(output))
    residual: FloatArray = frame.get_column(output).to_numpy().astype(np.float64, copy=False)
    groups = (
        frame.group_by("time", "underlying", "expiration")
        .agg(
            pl.len().alias("quotes"),
            pl.col(output).mean().alias("mean_residual"),
            (pl.col(output).pow(2).mean().sqrt()).alias("rmse"),
        )
        .sort("time", "underlying", "expiration")
        .to_dicts()
    )
    evidence = AnalysisResult(
        metadata=ResultMetadata(
            method="options.empirical_residual",
            method_version=1,
            parameters={
                "observed_column": observed,
                "expected_column": expected,
                "output_column": output,
                "definition": "observed_minus_expected",
            },
        ),
        metrics={
            "quote_count": residual.size,
            "mean_residual": float(residual.mean()),
            "median_residual": float(np.median(residual)),
            "rmse": float(np.sqrt(np.mean(np.square(residual)))),
            "positive_fraction": float(np.mean(residual > 0.0)),
        },
        tables={"surface_groups": tuple(cast(dict[str, JsonValue], row) for row in groups)},
    )
    return OptionFrameResult(frame=frame, evidence=evidence)


__all__ = [
    "OPTIONAL_CHAIN_COLUMNS",
    "REQUIRED_CHAIN_COLUMNS",
    "OptionChain",
    "OptionFrameResult",
    "delta_buckets",
    "empirical_residual",
    "validate_chain",
]
