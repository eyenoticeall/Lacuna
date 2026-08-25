"""Internal semantic-frame validation and serialization helpers."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from enum import Enum
from typing import Literal, TypeAlias

import polars as pl

from lacuna.adapters.polars import require_columns, to_polars
from lacuna.exceptions import DataContractError, MethodContractError
from lacuna.types import JsonValue

NullPolicy: TypeAlias = str
CopyClassification: TypeAlias = Literal[
    "zero_copy",
    "potentially_zero_copy",
    "one_copy",
    "materializing",
]


def _source_type(data: object) -> str:
    if isinstance(data, pl.LazyFrame):
        return "polars.LazyFrame"
    if isinstance(data, pl.DataFrame):
        return "polars.DataFrame"
    module = type(data).__module__.split(".", maxsplit=1)[0]
    return f"{module}.{type(data).__name__}"


@dataclass(frozen=True, slots=True)
class FrameDiagnostics:
    """Shape, adapter-copy, and materialization evidence for an input frame."""

    source_type: str
    rows: int
    columns: tuple[str, ...]
    lazy_input: bool
    materialized: bool
    adapter_copy: CopyClassification
    adapter_operations: tuple[str, ...]
    materialization_reason: str | None = None
    execution_operations: tuple[str, ...] = ()

    def with_execution(self, *operations: str) -> FrameDiagnostics:
        """Return diagnostics extended with result-affecting frame operations."""

        return replace(
            self,
            execution_operations=tuple(dict.fromkeys((*self.execution_operations, *operations))),
        )

    def to_parameters(self) -> dict[str, JsonValue]:
        """Return compact JSON-safe diagnostics for method metadata."""

        return {
            "source_type": self.source_type,
            "rows": self.rows,
            "columns": self.columns,
            "lazy_input": self.lazy_input,
            "materialized": self.materialized,
            "adapter_copy": self.adapter_copy,
            "adapter_operations": self.adapter_operations,
            "materialization_reason": self.materialization_reason,
            "execution_operations": self.execution_operations,
        }


def _copy_diagnostics(data: object) -> tuple[CopyClassification, tuple[str, ...]]:
    if isinstance(data, pl.LazyFrame):
        return "potentially_zero_copy", ("preserve_polars_lazy_plan",)
    if isinstance(data, pl.DataFrame):
        return "zero_copy", ("reuse_polars_dataframe",)
    if isinstance(data, pl.Series):
        return "zero_copy", ("polars_series_to_frame",)
    module = type(data).__module__.split(".", maxsplit=1)[0]
    if module == "numpy":
        return "potentially_zero_copy", ("numpy_to_polars",)
    if module == "pandas":
        return "one_copy", ("pandas_to_polars",)
    if hasattr(data, "__arrow_c_stream__"):
        return "potentially_zero_copy", ("arrow_c_stream_to_polars",)
    if isinstance(data, dict):
        return "one_copy", ("mapping_to_polars",)
    return "potentially_zero_copy", ("arrow_compatible_to_polars",)


def eager_frame(
    data: object,
    *,
    schema: Sequence[str] | None = None,
    required: Sequence[str] = (),
) -> tuple[pl.DataFrame, FrameDiagnostics]:
    """Normalize supported tabular input and deliberately materialize it."""

    lazy_input = isinstance(data, pl.LazyFrame)
    adapter_copy, adapter_operations = _copy_diagnostics(data)
    normalized = to_polars(data, schema=schema)
    require_columns(normalized, required)
    if isinstance(normalized, pl.LazyFrame):
        materialized = True
        frame = normalized.collect()
        adapter_copy = "materializing"
        materialization_reason = "domain method requires an eager frame"
    else:
        materialized = False
        frame = normalized
        materialization_reason = None
    return frame, FrameDiagnostics(
        source_type=_source_type(data),
        rows=frame.height,
        columns=tuple(frame.columns),
        lazy_input=lazy_input,
        materialized=materialized,
        adapter_copy=adapter_copy,
        adapter_operations=adapter_operations,
        materialization_reason=materialization_reason,
    )


def require_numeric(frame: pl.DataFrame, columns: Sequence[str]) -> None:
    """Require numeric physical dtypes for analytical value columns."""

    schema = frame.schema
    invalid = [column for column in columns if not schema[column].is_numeric()]
    if invalid:
        details = ", ".join(f"{column}={schema[column]}" for column in invalid)
        raise DataContractError(f"required numeric columns have invalid dtypes: {details}")


def require_no_nulls(frame: pl.DataFrame, columns: Sequence[str], *, name: str) -> None:
    """Reject null semantic keys with field-specific counts."""

    invalid = {
        column: int(frame.get_column(column).null_count())
        for column in columns
        if frame.get_column(column).null_count()
    }
    if invalid:
        details = ", ".join(f"{column}={count}" for column, count in invalid.items())
        raise DataContractError(f"{name} contains null semantic keys: {details}")


def _is_integral_float(series: pl.Series) -> bool:
    if not series.dtype.is_float():
        return False
    values = series.drop_nulls()
    if values.is_empty():
        return True
    invalid = values.is_infinite() | values.is_nan() | (values != values.floor())
    return not bool(invalid.any())


def require_time_key(frame: pl.DataFrame, column: str, *, name: str) -> None:
    """Require an ordered temporal value or whole-number observation index."""

    series = frame.get_column(column)
    dtype = series.dtype
    supported = (
        dtype == pl.Date
        or isinstance(dtype, (pl.Datetime, pl.Duration))
        or dtype.is_integer()
        or _is_integral_float(series)
    )
    if not supported:
        raise DataContractError(
            f"{name} time column {column!r} must be Date, Datetime, Duration, or a "
            f"whole-number observation index; got {dtype}"
        )


def require_identifier(frame: pl.DataFrame, column: str, *, name: str) -> None:
    """Require a stable scalar identifier representation."""

    series = frame.get_column(column)
    dtype = series.dtype
    supported = (
        dtype == pl.String
        or dtype == pl.Categorical
        or isinstance(dtype, pl.Enum)
        or dtype.is_integer()
        or _is_integral_float(series)
    )
    if not supported:
        raise DataContractError(
            f"{name} instrument column {column!r} must contain strings, categorical values, "
            f"or integer identifiers; got {dtype}"
        )


def validate_panel_schema(
    frame: pl.DataFrame,
    *,
    time: str,
    instrument: str,
    numeric: Sequence[str],
    name: str,
    unique: bool = True,
) -> None:
    """Validate the shared time, identity, and numeric panel contract."""

    if frame.is_empty():
        raise DataContractError(f"{name} must contain at least one row")
    require_no_nulls(frame, [time, instrument], name=name)
    require_time_key(frame, time, name=name)
    require_identifier(frame, instrument, name=name)
    require_numeric(frame, numeric)
    if unique:
        require_unique(frame, [time, instrument], name=name)


def validate_label_intervals(
    frame: pl.DataFrame,
    *,
    observation_time: str,
    name: str = "labels",
) -> None:
    """Validate optional half-open label intervals when external labels provide them."""

    interval_columns = {"label_start", "label_end"}
    present = interval_columns.intersection(frame.columns)
    if present and present != interval_columns:
        missing = sorted(interval_columns.difference(present))
        raise DataContractError(
            f"{name} interval metadata is incomplete; missing columns: {', '.join(missing)}"
        )
    if not present:
        return

    ordered = ["label_start", "label_end"]
    if "entry_time" in frame.columns:
        ordered.append("entry_time")
    require_no_nulls(frame, ordered, name=name)
    expected_dtype = frame.schema[observation_time]
    mismatched = [column for column in ordered if frame.schema[column] != expected_dtype]
    if mismatched:
        details = ", ".join(f"{column}={frame.schema[column]}" for column in mismatched)
        raise DataContractError(
            f"{name} interval columns must match {observation_time}={expected_dtype}; got {details}"
        )
    invalid_interval = frame.select((pl.col("label_start") >= pl.col("label_end")).sum()).item()
    if invalid_interval:
        raise DataContractError(
            f"{name} contains {invalid_interval} intervals that do not satisfy "
            "label_start < label_end"
        )
    if "entry_time" in frame.columns:
        invalid_entry = frame.select(
            (
                (pl.col("entry_time") < pl.col("label_start"))
                | (pl.col("entry_time") > pl.col("label_end"))
            ).sum()
        ).item()
        if invalid_entry:
            raise DataContractError(
                f"{name} contains {invalid_entry} entry times outside [label_start, label_end]"
            )


def require_compatible_keys(
    left: pl.DataFrame,
    right: pl.DataFrame,
    *,
    pairs: Sequence[tuple[str, str]],
) -> None:
    """Fail before a join when semantic key dtypes disagree."""

    mismatched = [
        (left_name, left.schema[left_name], right_name, right.schema[right_name])
        for left_name, right_name in pairs
        if left.schema[left_name] != right.schema[right_name]
    ]
    if mismatched:
        details = ", ".join(
            f"{left_name}={left_dtype} vs {right_name}={right_dtype}"
            for left_name, left_dtype, right_name, right_dtype in mismatched
        )
        raise DataContractError(f"aligned semantic keys must use matching dtypes: {details}")


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
        raise MethodContractError("null_policy must be 'drop' or 'raise'")
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
