"""Internal semantic-frame validation and serialization helpers."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import TypeAlias

import polars as pl

from lacuna.adapters import frame_summary, require_columns, to_polars
from lacuna.exceptions import DataContractError
from lacuna.types import JsonValue

NullPolicy: TypeAlias = str


@dataclass(frozen=True, slots=True)
class FrameDiagnostics:
    """Materialization and shape evidence for an input frame."""

    source_type: str
    rows: int
    columns: tuple[str, ...]
    materialized: bool

    def to_parameters(self) -> dict[str, JsonValue]:
        """Return compact JSON-safe diagnostics for method metadata."""

        return {
            "source_type": self.source_type,
            "rows": self.rows,
            "columns": self.columns,
            "materialized": self.materialized,
        }


def eager_frame(
    data: object,
    *,
    schema: Sequence[str] | None = None,
    required: Sequence[str] = (),
) -> tuple[pl.DataFrame, FrameDiagnostics]:
    """Normalize supported tabular input and deliberately materialize it."""

    normalized = to_polars(data, schema=schema)
    summary = frame_summary(normalized)
    require_columns(normalized, required)
    if isinstance(normalized, pl.LazyFrame):
        materialized = True
        frame = normalized.collect()
    else:
        materialized = False
        frame = normalized
    return frame, FrameDiagnostics(
        source_type=summary.source_type,
        rows=frame.height,
        columns=tuple(frame.columns),
        materialized=materialized,
    )


def require_numeric(frame: pl.DataFrame, columns: Sequence[str]) -> None:
    """Require numeric physical dtypes for analytical value columns."""

    schema = frame.schema
    invalid = [column for column in columns if not schema[column].is_numeric()]
    if invalid:
        details = ", ".join(f"{column}={schema[column]}" for column in invalid)
        raise DataContractError(f"required numeric columns have invalid dtypes: {details}")


def require_unique(frame: pl.DataFrame, columns: Sequence[str], *, name: str) -> None:
    """Reject duplicate logical keys rather than relying on row order."""

    if not columns or frame.is_empty():
        return
    duplicate_count = frame.select(pl.struct(columns).is_duplicated().sum()).item()
    if duplicate_count:
        joined = ", ".join(columns)
        raise DataContractError(
            f"{name} contains {duplicate_count} duplicate rows for logical key ({joined})"
        )


def paired_numeric_policy(
    frame: pl.DataFrame,
    columns: Sequence[str],
    *,
    null_policy: NullPolicy,
) -> tuple[pl.DataFrame, int]:
    """Apply a paired null policy and reject all infinite values."""

    if null_policy not in {"drop", "raise"}:
        raise ValueError("null_policy must be 'drop' or 'raise'")
    require_numeric(frame, columns)

    invalid_expression = pl.any_horizontal([pl.col(column).is_infinite() for column in columns])
    infinite_count = frame.select(invalid_expression.sum()).item()
    if infinite_count:
        raise DataContractError(
            f"numeric input contains {infinite_count} rows with positive or negative infinity"
        )

    missing_expression = pl.any_horizontal(
        [pl.col(column).is_null() | pl.col(column).is_nan() for column in columns]
    )
    missing_count = frame.select(missing_expression.sum()).item()
    if missing_count and null_policy == "raise":
        raise DataContractError(
            f"numeric input contains {missing_count} rows with null or NaN values"
        )
    if missing_count:
        return frame.filter(~missing_expression), int(missing_count)
    return frame, 0


def _json_cell(value: object) -> JsonValue:
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            return value.isoformat()
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return _json_cell(value.value)
    if isinstance(value, list | tuple):
        return tuple(_json_cell(item) for item in value)
    return str(value)


def frame_records(frame: pl.DataFrame) -> tuple[JsonValue, ...]:
    """Convert a compact evidence table to immutable JSON-compatible records."""

    return tuple({key: _json_cell(value) for key, value in row.items()} for row in frame.to_dicts())


def series_time_i64(series: pl.Series) -> list[int]:
    """Normalize supported temporal or integer values for native interval kernels."""

    dtype = series.dtype
    if dtype == pl.Date or isinstance(dtype, (pl.Datetime, pl.Duration)):
        return series.cast(pl.Int64).to_list()
    if dtype.is_integer():
        return series.cast(pl.Int64).to_list()
    raise DataContractError(
        f"time column {series.name!r} must be Date, Datetime, Duration, or integer; got {dtype}"
    )
