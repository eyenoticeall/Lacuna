"""Shared immutable results for optional adapter boundaries."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import polars as pl

from lacuna.adapters.polars import PolarsFrame, frame_summary, require_columns, to_polars
from lacuna.exceptions import DataContractError, MethodContractError
from lacuna.types import AnalysisResult


@dataclass(frozen=True, slots=True)
class AdaptedFrame:
    """A normalized frame together with inspectable adapter evidence."""

    frame: PolarsFrame
    evidence: AnalysisResult

    @property
    def columns(self) -> tuple[str, ...]:
        """Return normalized columns without collecting a lazy frame."""

        if isinstance(self.frame, pl.LazyFrame):
            return tuple(self.frame.collect_schema().names())
        return tuple(self.frame.columns)

    @property
    def lazy(self) -> bool:
        """Whether the normalized frame remains lazy."""

        return isinstance(self.frame, pl.LazyFrame)


def normalize_mapped_frame(
    data: object,
    *,
    columns: Mapping[str, str],
    required: Sequence[str],
    collect: bool,
    include_pandas_index: bool = False,
) -> tuple[PolarsFrame, tuple[str, ...]]:
    """Rename explicit source fields to canonical names without silent collisions."""

    if not isinstance(collect, bool):
        raise MethodContractError("collect must be boolean")
    if not columns:
        raise MethodContractError("columns must contain at least one canonical-to-source mapping")
    if any(
        not isinstance(canonical, str) or not canonical or not isinstance(source, str) or not source
        for canonical, source in columns.items()
    ):
        raise MethodContractError("column mappings must use non-empty string names")
    if len(set(columns.values())) != len(columns):
        raise MethodContractError("a source column cannot map to multiple canonical columns")
    if any(not isinstance(column, str) or not column for column in required):
        raise MethodContractError("required must contain non-empty canonical column names")
    unknown_required = sorted(set(required).difference(columns))
    if unknown_required:
        raise MethodContractError(
            f"required canonical columns are not mapped: {', '.join(unknown_required)}"
        )

    frame = to_polars(
        data,
        collect=collect,
        include_pandas_index=include_pandas_index,
    )
    original_columns = frame_summary(frame).columns
    require_columns(frame, [columns[column] for column in required])
    rename = {source: canonical for canonical, source in columns.items() if source != canonical}
    moving_sources = set(rename)
    collisions = sorted(
        canonical
        for source, canonical in rename.items()
        if canonical in original_columns and canonical not in moving_sources and canonical != source
    )
    if collisions:
        raise DataContractError(
            f"normalization would overwrite existing columns: {', '.join(collisions)}"
        )
    normalized = frame.rename(rename)
    require_columns(normalized, required)
    return normalized, original_columns


__all__ = ["AdaptedFrame"]
