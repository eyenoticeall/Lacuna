"""Polars-first normalization at Lacuna's dataframe boundary."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, TypeAlias

import numpy as np
import polars as pl

from lacuna.exceptions import DataContractError

PolarsFrame: TypeAlias = pl.DataFrame | pl.LazyFrame


@dataclass(frozen=True, slots=True)
class FrameSummary:
    """Cheap structural information that does not collect a lazy frame."""

    columns: tuple[str, ...]
    lazy: bool
    source_type: str


def _as_dataframe(frame: pl.DataFrame | pl.Series) -> pl.DataFrame:
    return frame.to_frame() if isinstance(frame, pl.Series) else frame


def _from_numpy(data: np.ndarray[Any, Any], schema: Sequence[str] | None) -> pl.DataFrame:
    if data.ndim == 1:
        if schema is not None and len(schema) != 1:
            raise DataContractError("one-dimensional NumPy input requires exactly one column name")
        name = schema[0] if schema else "value"
        return pl.Series(name, data).to_frame()
    if data.ndim != 2:
        raise DataContractError("NumPy input must be one- or two-dimensional")
    if schema is None:
        raise DataContractError("two-dimensional NumPy input requires an explicit schema")
    if len(schema) != data.shape[1]:
        raise DataContractError("schema length must match the NumPy array's column count")
    return pl.from_numpy(data, schema=list(schema), orient="row")


def to_polars(
    data: object,
    *,
    schema: Sequence[str] | None = None,
    collect: bool = False,
    include_pandas_index: bool = False,
) -> PolarsFrame:
    """Normalize a supported dataframe-like object to Polars.

    Polars inputs stay on the preferred path. Lazy inputs are not materialized
    unless ``collect=True``. NumPy, pandas, Arrow C Stream producers, mappings,
    and objects accepted by ``polars.from_arrow`` are supported at the edge.
    """

    frame: PolarsFrame
    if isinstance(data, pl.Series):
        frame = data.to_frame()
    elif isinstance(data, pl.DataFrame | pl.LazyFrame):
        frame = data
    elif isinstance(data, np.ndarray):
        frame = _from_numpy(data, schema)
    elif isinstance(data, Mapping):
        frame = pl.DataFrame(data)
    elif type(data).__module__.split(".", maxsplit=1)[0] == "pandas":
        frame = _as_dataframe(pl.from_pandas(data, include_index=include_pandas_index))
    elif hasattr(data, "__arrow_c_stream__"):
        frame = _as_dataframe(pl.from_arrow(data))
    else:
        try:
            frame = _as_dataframe(pl.from_arrow(data))
        except (TypeError, ValueError) as error:
            message = f"unsupported dataframe input: {type(data).__module__}.{type(data).__name__}"
            raise DataContractError(message) from error

    if collect and isinstance(frame, pl.LazyFrame):
        return frame.collect()
    return frame


def frame_summary(frame: PolarsFrame) -> FrameSummary:
    """Describe a frame without materializing a lazy query."""

    if isinstance(frame, pl.LazyFrame):
        columns = tuple(frame.collect_schema().names())
        return FrameSummary(columns=columns, lazy=True, source_type="polars.LazyFrame")
    return FrameSummary(
        columns=tuple(frame.columns),
        lazy=False,
        source_type="polars.DataFrame",
    )


def require_columns(frame: PolarsFrame, required: Sequence[str]) -> PolarsFrame:
    """Validate required column names without collecting lazy input."""

    summary = frame_summary(frame)
    missing = sorted(set(required).difference(summary.columns))
    if missing:
        formatted = ", ".join(missing)
        raise DataContractError(f"missing required columns: {formatted}")
    return frame
