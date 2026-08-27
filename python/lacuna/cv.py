"""Temporal cross-validation with inspectable folds, purging, and embargo."""

from __future__ import annotations

import calendar
import re
from bisect import bisect_right
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from itertools import combinations
from math import comb
from typing import Literal, TypeAlias, cast

import numpy as np
import numpy.typing as npt
import polars as pl

from lacuna._carriers import CompactFoldBuffer
from lacuna._frames import eager_frame, series_time_i64
from lacuna._native_arrays import readonly_int64, readonly_int64_matrix
from lacuna.exceptions import DataContractError, MethodContractError
from lacuna.types import AnalysisResult, JsonValue, ResultMetadata

Duration: TypeAlias = str | int
TimeValue: TypeAlias = int | date | datetime
_DURATION_PATTERN = re.compile(r"^(?P<count>[1-9][0-9]*)(?P<unit>D|W|M|Y)$", re.IGNORECASE)
_CPCV_NATIVE_ROLE_EVALUATION_THRESHOLD = 100_000


@dataclass(frozen=True, slots=True)
class _CalendarSpan:
    months: int = 0
    days: int = 0


@dataclass(frozen=True, slots=True)
class Fold:
    """One temporal fold represented by stable source-row indices."""

    fold: int
    train_indices: tuple[int, ...]
    test_indices: tuple[int, ...]
    purged_indices: tuple[int, ...] = ()
    embargoed_indices: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class SplitResult:
    """Inspectable temporal folds and their structured evidence."""

    folds: tuple[Fold, ...]
    evidence: AnalysisResult

    def __iter__(
        self,
    ) -> Iterator[
        tuple[
            np.ndarray[tuple[int], np.dtype[np.int64]], np.ndarray[tuple[int], np.dtype[np.int64]]
        ]
    ]:
        for fold in self.folds:
            yield (
                np.asarray(fold.train_indices, dtype=np.int64),
                np.asarray(fold.test_indices, dtype=np.int64),
            )

    @property
    def fold_table(self) -> object:
        """Return the JSON-compatible fold table used for visualization."""

        return self.evidence.table("folds")

    def to_json(self, *, indent: int | None = 2) -> str:
        """Serialize split configuration and fold evidence."""

        return self.evidence.to_json(indent=indent)


@dataclass(frozen=True, slots=True)
class CPCVPath:
    """One reconstructed CPCV path over every chronological group."""

    path: int
    fold_by_group: tuple[int, ...]
    test_indices: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class CombinatorialSplitResult:
    """Inspectable CPCV combinations and reconstructed backtest paths."""

    folds: tuple[Fold, ...]
    paths: tuple[CPCVPath, ...]
    evidence: AnalysisResult

    def __iter__(
        self,
    ) -> Iterator[
        tuple[
            np.ndarray[tuple[int], np.dtype[np.int64]], np.ndarray[tuple[int], np.dtype[np.int64]]
        ]
    ]:
        for fold in self.folds:
            yield (
                np.asarray(fold.train_indices, dtype=np.int64),
                np.asarray(fold.test_indices, dtype=np.int64),
            )

    @property
    def fold_table(self) -> object:
        """Return the JSON-compatible fold table used for visualization."""

        return self.evidence.table("folds")

    @property
    def path_table(self) -> object:
        """Return the group-to-fold assignments for every reconstructed path."""

        return self.evidence.table("paths")

    def to_json(self, *, indent: int | None = 2) -> str:
        """Serialize split configuration, combinations, and path evidence."""

        return self.evidence.to_json(indent=indent)


def _parse_duration(value: Duration, *, name: str) -> int | _CalendarSpan:
    if isinstance(value, bool):
        raise MethodContractError(f"{name} must be a positive observation count or duration")
    if isinstance(value, int):
        if value < 1:
            raise MethodContractError(f"{name} must be positive")
        return value
    match = _DURATION_PATTERN.fullmatch(value.strip())
    if match is None:
        raise MethodContractError(
            f"invalid {name} duration {value!r}; use an observation count or D/W/M/Y string"
        )
    count = int(match.group("count"))
    unit = match.group("unit").upper()
    if unit == "D":
        return _CalendarSpan(days=count)
    if unit == "W":
        return _CalendarSpan(days=count * 7)
    if unit == "M":
        return _CalendarSpan(months=count)
    return _CalendarSpan(months=count * 12)


def _add_months(value: date | datetime, months: int) -> date | datetime:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def _add_span(value: date | datetime, span: _CalendarSpan) -> date | datetime:
    shifted = _add_months(value, span.months)
    return shifted + timedelta(days=span.days)


def _validated_times(values: Sequence[object]) -> list[TimeValue]:
    result: list[TimeValue] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, int | date):
            raise DataContractError("observation times must be integer, Date, or Datetime values")
        result.append(value)
    return result


def _calendar_times(values: Sequence[TimeValue]) -> list[date | datetime]:
    if any(not isinstance(value, date) for value in values):
        raise DataContractError("calendar durations require Date or Datetime observation times")
    return [value for value in values if isinstance(value, date)]


def _validate_span_family(*spans: int | _CalendarSpan) -> bool:
    observation_based = all(isinstance(span, int) for span in spans)
    calendar_based = all(isinstance(span, _CalendarSpan) for span in spans)
    if not observation_based and not calendar_based:
        raise MethodContractError("train, test, and step must use the same duration convention")
    return observation_based


def _role_rows(
    fold: Fold,
    source_times: Sequence[TimeValue],
) -> list[dict[str, JsonValue]]:
    rows: list[dict[str, JsonValue]] = []
    roles = (
        ("train", fold.train_indices),
        ("purge", fold.purged_indices),
        ("test", fold.test_indices),
        ("embargo", fold.embargoed_indices),
    )
    for role, indices in roles:
        if indices:
            start: TimeValue | None = min(source_times[index] for index in indices)
            end: TimeValue | None = max(source_times[index] for index in indices)
        else:
            start = None
            end = None
        rows.append(
            {
                "fold": fold.fold,
                "role": role,
                "start": start.isoformat() if isinstance(start, date) else start,
                "end": end.isoformat() if isinstance(end, date) else end,
                "n_observations": len(indices),
            }
        )
    return rows


def _split_evidence(
    *,
    method: str,
    parameters: dict[str, JsonValue],
    folds: Sequence[Fold],
    source_times: Sequence[TimeValue],
) -> AnalysisResult:
    fold_rows = [row for fold in folds for row in _role_rows(fold, source_times)]
    return AnalysisResult(
        metadata=ResultMetadata(method=method, method_version=1, parameters=parameters),
        metrics={
            "n_folds": len(folds),
            "purged_observations": sum(len(fold.purged_indices) for fold in folds),
            "embargoed_observations": sum(len(fold.embargoed_indices) for fold in folds),
        },
        tables={"folds": tuple(fold_rows)},
    )


@dataclass(frozen=True, slots=True)
class WalkForward:
    """Chronological expanding or rolling walk-forward splitter."""

    train: Duration
    test: Duration
    step: Duration
    mode: Literal["expanding", "rolling"] = "expanding"
    allow_incomplete: bool = False

    def __post_init__(self) -> None:
        if self.mode not in {"expanding", "rolling"}:
            raise MethodContractError("mode must be 'expanding' or 'rolling'")
        train_span = _parse_duration(self.train, name="train")
        test_span = _parse_duration(self.test, name="test")
        step_span = _parse_duration(self.step, name="step")
        _validate_span_family(train_span, test_span, step_span)

    def split(self, data: object, *, time: str = "time") -> SplitResult:
        """Create deterministic folds over sorted unique observation times."""

        frame, diagnostics = eager_frame(data, required=[time])
        if frame.is_empty():
            raise DataContractError("walk-forward input must contain at least one row")
        if frame.get_column(time).null_count():
            raise DataContractError("walk-forward observation times must not be null")
        indexed = frame.with_row_index("_source_index")
        unique_times = _validated_times(indexed.get_column(time).unique().sort().to_list())
        train_span = _parse_duration(self.train, name="train")
        test_span = _parse_duration(self.test, name="test")
        step_span = _parse_duration(self.step, name="step")
        observation_based = _validate_span_family(train_span, test_span, step_span)
        folds: list[Fold] = []

        if observation_based:
            assert isinstance(train_span, int)
            assert isinstance(test_span, int)
            assert isinstance(step_span, int)
            test_start = train_span
            while test_start < len(unique_times):
                test_end = min(test_start + test_span, len(unique_times))
                if test_end - test_start < test_span and not self.allow_incomplete:
                    break
                train_start = 0 if self.mode == "expanding" else max(0, test_start - train_span)
                train_times = set(unique_times[train_start:test_start])
                test_times = set(unique_times[test_start:test_end])
                train_indices = indexed.filter(pl.col(time).is_in(train_times)).get_column(
                    "_source_index"
                )
                test_indices = indexed.filter(pl.col(time).is_in(test_times)).get_column(
                    "_source_index"
                )
                if train_indices.len() and test_indices.len():
                    folds.append(
                        Fold(
                            fold=len(folds),
                            train_indices=tuple(train_indices.to_list()),
                            test_indices=tuple(test_indices.to_list()),
                        )
                    )
                test_start += step_span
        else:
            assert isinstance(train_span, _CalendarSpan)
            assert isinstance(test_span, _CalendarSpan)
            assert isinstance(step_span, _CalendarSpan)
            calendar_times = _calendar_times(unique_times)
            train_origin = calendar_times[0]
            test_start_time = _add_span(train_origin, train_span)
            while test_start_time <= calendar_times[-1]:
                test_end_time = _add_span(test_start_time, test_span)
                if test_end_time > calendar_times[-1] and not self.allow_incomplete:
                    break
                if self.mode == "expanding":
                    train_start_time = train_origin
                else:
                    train_start_time = _add_span(
                        test_start_time,
                        _CalendarSpan(months=-train_span.months, days=-train_span.days),
                    )
                train_mask = (pl.col(time) >= pl.lit(train_start_time)) & (
                    pl.col(time) < pl.lit(test_start_time)
                )
                test_mask = (pl.col(time) >= pl.lit(test_start_time)) & (
                    pl.col(time) < pl.lit(test_end_time)
                )
                train_indices = indexed.filter(train_mask).get_column("_source_index")
                test_indices = indexed.filter(test_mask).get_column("_source_index")
                if train_indices.len() and test_indices.len():
                    folds.append(
                        Fold(
                            fold=len(folds),
                            train_indices=tuple(train_indices.to_list()),
                            test_indices=tuple(test_indices.to_list()),
                        )
                    )
                test_start_time = _add_span(test_start_time, step_span)

        if not folds:
            raise DataContractError("walk-forward configuration produced no complete folds")
        source_times = _validated_times(indexed.sort("_source_index").get_column(time).to_list())
        evidence = _split_evidence(
            method="cv.walk_forward",
            parameters={
                "train": self.train,
                "test": self.test,
                "step": self.step,
                "mode": self.mode,
                "allow_incomplete": self.allow_incomplete,
                "shuffle": False,
                "interval_closure": "[start, end)",
                "time_column": time,
                "input": diagnostics.to_parameters(),
            },
            folds=folds,
            source_times=source_times,
        )
        return SplitResult(folds=tuple(folds), evidence=evidence)


def _merged_intervals(starts: Sequence[int], ends: Sequence[int]) -> list[tuple[int, int]]:
    intervals = sorted(zip(starts, ends, strict=True))
    merged: list[tuple[int, int]] = []
    for start, end in intervals:
        if end <= start:
            raise DataContractError("label intervals must satisfy label_start < label_end")
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        else:
            previous_start, previous_end = merged[-1]
            merged[-1] = (previous_start, max(previous_end, end))
    return merged


def _literal_purge_mask(
    train_starts: Sequence[int],
    train_ends: Sequence[int],
    test_starts: Sequence[int],
    test_ends: Sequence[int],
) -> list[bool]:
    merged = _merged_intervals(test_starts, test_ends)
    merged_ends = [end for _, end in merged]
    result: list[bool] = []
    for train_start, train_end in zip(train_starts, train_ends, strict=True):
        if train_end <= train_start:
            raise DataContractError("label intervals must satisfy label_start < label_end")
        index = bisect_right(merged_ends, train_start)
        result.append(index < len(merged) and merged[index][0] < train_end)
    return result


def _reference_purge_mask(
    train_starts: Sequence[int],
    train_ends: Sequence[int],
    test_starts: Sequence[int],
    test_ends: Sequence[int],
) -> list[bool]:
    """Vectorized half-open interval oracle retaining the literal differential path."""

    train_start_array: npt.NDArray[np.int64] = np.asarray(train_starts, dtype=np.int64)
    train_end_array: npt.NDArray[np.int64] = np.asarray(train_ends, dtype=np.int64)
    test_start_array: npt.NDArray[np.int64] = np.asarray(test_starts, dtype=np.int64)
    test_end_array: npt.NDArray[np.int64] = np.asarray(test_ends, dtype=np.int64)
    if train_start_array.shape != train_end_array.shape:
        raise DataContractError("aligned training interval arrays must have equal lengths")
    if test_start_array.shape != test_end_array.shape:
        raise DataContractError("aligned test interval arrays must have equal lengths")
    if np.any(train_end_array <= train_start_array) or np.any(test_end_array <= test_start_array):
        raise DataContractError("label intervals must satisfy label_start < label_end")
    if test_start_array.size == 0:
        return cast(list[bool], np.zeros(train_start_array.size, dtype=np.bool_).tolist())

    order: npt.NDArray[np.intp] = np.lexsort((test_end_array, test_start_array))
    ordered_starts: npt.NDArray[np.int64] = test_start_array[order]
    prefix_max_end: npt.NDArray[np.int64] = np.maximum.accumulate(test_end_array[order])
    eligible_position: npt.NDArray[np.intp] = (
        np.searchsorted(ordered_starts, train_end_array, side="left") - 1
    )
    overlaps: npt.NDArray[np.bool_] = np.zeros(train_start_array.size, dtype=np.bool_)
    eligible: npt.NDArray[np.bool_] = eligible_position >= 0
    overlaps[eligible] = prefix_max_end[eligible_position[eligible]] > train_start_array[eligible]
    return cast(list[bool], overlaps.tolist())


def _purge_mask(
    train_starts: Sequence[int],
    train_ends: Sequence[int],
    test_starts: Sequence[int],
    test_ends: Sequence[int],
    *,
    use_native: bool,
) -> tuple[list[bool], str]:
    if use_native:
        try:
            from lacuna import _native

            starts = readonly_int64(train_starts, name="train_starts").values
            ends = readonly_int64(train_ends, name="train_ends").values
            held_starts = readonly_int64(test_starts, name="test_starts").values
            held_ends = readonly_int64(test_ends, name="test_ends").values
            return (
                _native.interval_purge(
                    starts,
                    ends,
                    held_starts,
                    held_ends,
                )
                .astype(np.bool_, copy=False)
                .tolist(),
                "rust_native",
            )
        except (ImportError, AttributeError):
            pass
    return (
        _reference_purge_mask(train_starts, train_ends, test_starts, test_ends),
        "python_reference",
    )


def _native_cpcv_assembly(
    *,
    row_groups: npt.NDArray[np.int64],
    row_periods: npt.NDArray[np.int64],
    starts: npt.NDArray[np.int64],
    ends: npt.NDArray[np.int64],
    group_end_periods: npt.NDArray[np.int64],
    combination_groups: npt.NDArray[np.int64],
    embargo: int,
    group_count: int,
) -> CompactFoldBuffer | None:
    """Call the optional coarse-grained native assembler with checked typed buffers."""

    try:
        from lacuna import _native

        native_assembly = _native.cpcv_fold_assembly
    except (ImportError, AttributeError):
        return None
    normalized = (
        readonly_int64(row_groups, name="row_groups").values,
        readonly_int64(row_periods, name="row_periods").values,
        readonly_int64(starts, name="starts").values,
        readonly_int64(ends, name="ends").values,
        readonly_int64(group_end_periods, name="group_end_periods").values,
        readonly_int64_matrix(combination_groups, name="combination_groups").values,
    )
    try:
        output = native_assembly(*normalized, embargo)
    except ValueError as error:
        raise DataContractError(f"native CPCV assembly failed validation: {error}") from error
    return CompactFoldBuffer(
        row_count=int(row_groups.size),
        group_count=group_count,
        train_indices=output[0],
        train_offsets=output[1],
        test_indices=output[2],
        test_offsets=output[3],
        purged_indices=output[4],
        purged_offsets=output[5],
        embargoed_indices=output[6],
        embargoed_offsets=output[7],
        path_fold_by_group=output[8],
        path_offsets=output[9],
    )


def _project_native_cpcv(
    buffer: CompactFoldBuffer,
    *,
    group_rows: Sequence[Sequence[int]],
) -> tuple[list[Fold], tuple[CPCVPath, ...]]:
    folds = [
        Fold(
            fold=fold,
            train_indices=buffer.role(fold, "train"),
            test_indices=buffer.role(fold, "test"),
            purged_indices=buffer.role(fold, "purged"),
            embargoed_indices=buffer.role(fold, "embargoed"),
        )
        for fold in range(buffer.fold_count)
    ]
    path_test_indices = tuple(index for rows in group_rows for index in rows)
    paths = tuple(
        CPCVPath(
            path=path,
            fold_by_group=buffer.path(path),
            test_indices=path_test_indices,
        )
        for path in range(buffer.path_count)
    )
    return folds, paths


@dataclass(frozen=True, slots=True)
class PurgedKFold:
    """Chronological K-fold splitter with interval purging and optional embargo."""

    n_splits: int = 5
    embargo: int = 0
    use_native: bool = True

    def __post_init__(self) -> None:
        if self.n_splits < 2:
            raise MethodContractError("n_splits must be at least 2")
        if self.embargo < 0:
            raise MethodContractError("embargo must be a non-negative observation count")

    def split(
        self,
        data: object,
        *,
        time: str = "observation_time",
        label_start: str = "label_start",
        label_end: str = "label_end",
    ) -> SplitResult:
        """Split rows, purge overlapping label intervals, then apply embargo."""

        frame, diagnostics = eager_frame(data, required=[time, label_start, label_end])
        if frame.is_empty():
            raise DataContractError("purged split input must contain at least one row")
        if any(frame.get_column(column).null_count() for column in (time, label_start, label_end)):
            raise DataContractError("split time and label interval columns must not contain nulls")
        if frame.schema[label_start] != frame.schema[label_end]:
            raise DataContractError("label_start and label_end must have the same physical dtype")
        indexed = frame.with_row_index("_source_index")
        starts = series_time_i64(indexed.get_column(label_start))
        ends = series_time_i64(indexed.get_column(label_end))
        if any(end <= start for start, end in zip(starts, ends, strict=True)):
            raise DataContractError("label intervals must satisfy label_start < label_end")
        unique_times = _validated_times(indexed.get_column(time).unique().sort().to_list())
        if len(unique_times) < self.n_splits:
            raise DataContractError("n_splits cannot exceed the number of distinct periods")
        period_groups = [group.tolist() for group in np.array_split(unique_times, self.n_splits)]
        folds: list[Fold] = []
        backends: set[str] = set()
        period_positions = {value: position for position, value in enumerate(unique_times)}
        for fold_number, test_times in enumerate(period_groups):
            test_time_set = set(test_times)
            test_index_series = indexed.filter(pl.col(time).is_in(test_time_set)).get_column(
                "_source_index"
            )
            test_indices: list[int] = test_index_series.to_list()
            candidate_indices: list[int] = (
                indexed.filter(~pl.col(time).is_in(test_time_set))
                .get_column("_source_index")
                .to_list()
            )
            mask, backend = _purge_mask(
                [starts[index] for index in candidate_indices],
                [ends[index] for index in candidate_indices],
                [starts[index] for index in test_indices],
                [ends[index] for index in test_indices],
                use_native=self.use_native,
            )
            backends.add(backend)
            purged = [
                index for index, overlaps in zip(candidate_indices, mask, strict=True) if overlaps
            ]
            retained = [
                index
                for index, overlaps in zip(candidate_indices, mask, strict=True)
                if not overlaps
            ]
            embargoed: list[int] = []
            if self.embargo:
                final_test_period = max(period_positions[value] for value in test_times)
                embargo_times = set(
                    unique_times[final_test_period + 1 : final_test_period + 1 + self.embargo]
                )
                embargoed = (
                    indexed.filter(
                        pl.col("_source_index").is_in(retained) & pl.col(time).is_in(embargo_times)
                    )
                    .get_column("_source_index")
                    .to_list()
                )
                embargoed_set = set(embargoed)
                retained = [index for index in retained if index not in embargoed_set]
            folds.append(
                Fold(
                    fold=fold_number,
                    train_indices=tuple(retained),
                    test_indices=tuple(test_indices),
                    purged_indices=tuple(purged),
                    embargoed_indices=tuple(embargoed),
                )
            )

        source_times = _validated_times(indexed.sort("_source_index").get_column(time).to_list())
        evidence = _split_evidence(
            method="cv.purged_kfold",
            parameters={
                "n_splits": self.n_splits,
                "embargo_observations": self.embargo,
                "interval_closure": "[label_start, label_end)",
                "time_column": time,
                "label_start_column": label_start,
                "label_end_column": label_end,
                "backend": "+".join(sorted(backends)),
                "input": diagnostics.to_parameters(),
            },
            folds=folds,
            source_times=source_times,
        )
        return SplitResult(folds=tuple(folds), evidence=evidence)


@dataclass(frozen=True, slots=True)
class CombinatorialPurgedKFold:
    """Combinatorial purged cross-validation with explicit path reconstruction.

    Distinct observation times are divided into contiguous groups. Every
    ``n_test_groups`` combination is held out once, overlapping training-label
    intervals are purged, and an observation-count embargo is applied after
    each held-out group. The result includes every split and a deterministic
    assignment of test-group predictions to complete chronological paths.
    """

    n_groups: int = 6
    n_test_groups: int = 2
    embargo: int = 0
    max_combinations: int = 10_000
    use_native: bool = True

    def __post_init__(self) -> None:
        integer_parameters = {
            "n_groups": self.n_groups,
            "n_test_groups": self.n_test_groups,
            "embargo": self.embargo,
            "max_combinations": self.max_combinations,
        }
        invalid = [
            name
            for name, value in integer_parameters.items()
            if isinstance(value, bool) or not isinstance(value, int)
        ]
        if invalid:
            raise MethodContractError(
                f"CPCV integer parameters have invalid types: {', '.join(invalid)}"
            )
        if self.n_groups < 2:
            raise MethodContractError("n_groups must be at least 2")
        if not 1 <= self.n_test_groups < self.n_groups:
            raise MethodContractError("n_test_groups must be between 1 and n_groups - 1")
        if self.embargo < 0:
            raise MethodContractError("embargo must be a non-negative observation count")
        if self.max_combinations < 1:
            raise MethodContractError("max_combinations must be positive")
        if comb(self.n_groups, self.n_test_groups) > self.max_combinations:
            raise MethodContractError(
                "CPCV combination count exceeds max_combinations; reduce the group count "
                "or raise the explicit safety limit"
            )

    def split(
        self,
        data: object,
        *,
        time: str = "observation_time",
        label_start: str = "label_start",
        label_end: str = "label_end",
    ) -> CombinatorialSplitResult:
        """Generate purged combinations and reconstruct full test paths."""

        frame, diagnostics = eager_frame(data, required=[time, label_start, label_end])
        if frame.is_empty():
            raise DataContractError("CPCV input must contain at least one row")
        if any(frame.get_column(column).null_count() for column in (time, label_start, label_end)):
            raise DataContractError("CPCV time and label interval columns must not contain nulls")
        if frame.schema[label_start] != frame.schema[label_end]:
            raise DataContractError("label_start and label_end must have the same physical dtype")

        indexed = frame.with_row_index("_source_index")
        starts = series_time_i64(indexed.get_column(label_start))
        ends = series_time_i64(indexed.get_column(label_end))
        if any(end <= start for start, end in zip(starts, ends, strict=True)):
            raise DataContractError("label intervals must satisfy label_start < label_end")
        unique_times = _validated_times(indexed.get_column(time).unique().sort().to_list())
        if len(unique_times) < self.n_groups:
            raise DataContractError("n_groups cannot exceed the number of distinct periods")

        period_groups = [
            tuple(group.tolist()) for group in np.array_split(unique_times, self.n_groups)
        ]
        # Every unique value was validated above, so the source-order projection
        # cannot introduce a new temporal type.
        source_times = cast(list[TimeValue], indexed.get_column(time).to_list())
        time_to_group = {
            value: group for group, group_times in enumerate(period_groups) for value in group_times
        }
        period_positions = {value: position for position, value in enumerate(unique_times)}
        row_groups: npt.NDArray[np.int64] = np.fromiter(
            (time_to_group[value] for value in source_times),
            dtype=np.int64,
            count=len(source_times),
        )
        row_period_positions: npt.NDArray[np.int64] = np.fromiter(
            (period_positions[value] for value in source_times),
            dtype=np.int64,
            count=len(source_times),
        )
        ordered_source_indices: list[int] = (
            indexed.sort([time, "_source_index"]).get_column("_source_index").to_list()
        )
        mutable_group_rows: list[list[int]] = [[] for _ in range(self.n_groups)]
        for source_index in ordered_source_indices:
            mutable_group_rows[int(row_groups[source_index])].append(source_index)
        group_rows = [tuple(rows) for rows in mutable_group_rows]
        test_combinations = tuple(combinations(range(self.n_groups), self.n_test_groups))
        start_array: npt.NDArray[np.int64] = np.asarray(starts, dtype=np.int64)
        end_array: npt.NDArray[np.int64] = np.asarray(ends, dtype=np.int64)
        combination_array: npt.NDArray[np.int64] = np.asarray(
            test_combinations,
            dtype=np.int64,
        )
        group_end_periods: npt.NDArray[np.int64] = np.fromiter(
            (
                max(period_positions[value] for value in group_times)
                for group_times in period_groups
            ),
            dtype=np.int64,
            count=self.n_groups,
        )
        role_evaluations = len(source_times) * len(test_combinations)
        native_buffer = (
            _native_cpcv_assembly(
                row_groups=row_groups,
                row_periods=row_period_positions,
                starts=start_array,
                ends=end_array,
                group_end_periods=group_end_periods,
                combination_groups=combination_array,
                embargo=self.embargo,
                group_count=self.n_groups,
            )
            if self.use_native and role_evaluations >= _CPCV_NATIVE_ROLE_EVALUATION_THRESHOLD
            else None
        )
        backends: set[str]
        if native_buffer is not None:
            folds, paths = _project_native_cpcv(native_buffer, group_rows=group_rows)
            backends = {"rust_native"}
        else:
            folds = []
            backends = set()
            for fold_number, test_groups in enumerate(test_combinations):
                test_group_array: npt.NDArray[np.int64] = np.fromiter(
                    test_groups,
                    dtype=np.int64,
                )
                test_row_mask: npt.NDArray[np.bool_] = np.isin(row_groups, test_group_array)
                test_index_array: npt.NDArray[np.intp] = np.flatnonzero(test_row_mask)
                candidate_index_array: npt.NDArray[np.intp] = np.flatnonzero(~test_row_mask)
                test_indices = test_index_array.tolist()
                mask, backend = _purge_mask(
                    start_array[candidate_index_array],
                    end_array[candidate_index_array],
                    start_array[test_index_array],
                    end_array[test_index_array],
                    use_native=self.use_native,
                )
                backends.add(backend)
                overlap_mask: npt.NDArray[np.bool_] = np.asarray(mask, dtype=np.bool_)
                purged = candidate_index_array[overlap_mask].tolist()
                retained_array = candidate_index_array[~overlap_mask]

                embargo_positions: set[int] = set()
                if self.embargo:
                    for group in test_groups:
                        final_period = int(group_end_periods[group])
                        embargo_positions.update(
                            range(
                                final_period + 1,
                                min(final_period + 1 + self.embargo, len(unique_times)),
                            )
                        )
                if embargo_positions:
                    embargo_position_array: npt.NDArray[np.int64] = np.fromiter(
                        sorted(embargo_positions),
                        dtype=np.int64,
                    )
                    embargo_mask: npt.NDArray[np.bool_] = np.isin(
                        row_period_positions[retained_array],
                        embargo_position_array,
                    )
                    embargoed = retained_array[embargo_mask].tolist()
                    retained = retained_array[~embargo_mask].tolist()
                else:
                    embargoed = []
                    retained = retained_array.tolist()
                folds.append(
                    Fold(
                        fold=fold_number,
                        train_indices=tuple(retained),
                        test_indices=tuple(test_indices),
                        purged_indices=tuple(purged),
                        embargoed_indices=tuple(embargoed),
                    )
                )

            n_paths = comb(self.n_groups - 1, self.n_test_groups - 1)
            fold_by_path = [[-1] * self.n_groups for _ in range(n_paths)]
            for group in range(self.n_groups):
                group_folds = [
                    fold_number
                    for fold_number, test_groups in enumerate(test_combinations)
                    if group in test_groups
                ]
                if len(group_folds) != n_paths:  # pragma: no cover - combinatorial invariant
                    raise RuntimeError("invalid CPCV group incidence count")
                for path_index, fold_number in enumerate(group_folds):
                    fold_by_path[path_index][group] = fold_number

            path_test_indices = tuple(index for rows in group_rows for index in rows)
            paths = tuple(
                CPCVPath(
                    path=path_index,
                    fold_by_group=tuple(fold_numbers),
                    test_indices=path_test_indices,
                )
                for path_index, fold_numbers in enumerate(fold_by_path)
            )
        path_rows: list[dict[str, JsonValue]] = []
        for cpcv_path in paths:
            for group, fold_number in enumerate(cpcv_path.fold_by_group):
                group_times = period_groups[group]
                path_rows.append(
                    {
                        "path": cpcv_path.path,
                        "group": group,
                        "fold": fold_number,
                        "start": (
                            min(group_times).isoformat()
                            if isinstance(min(group_times), date)
                            else min(group_times)
                        ),
                        "end": (
                            max(group_times).isoformat()
                            if isinstance(max(group_times), date)
                            else max(group_times)
                        ),
                        "n_observations": len(group_rows[group]),
                    }
                )
        group_table: list[dict[str, JsonValue]] = []
        for group, (group_times, rows) in enumerate(zip(period_groups, group_rows, strict=True)):
            group_table.append(
                {
                    "group": group,
                    "start": (
                        min(group_times).isoformat()
                        if isinstance(min(group_times), date)
                        else min(group_times)
                    ),
                    "end": (
                        max(group_times).isoformat()
                        if isinstance(max(group_times), date)
                        else max(group_times)
                    ),
                    "n_periods": len(group_times),
                    "n_observations": len(rows),
                }
            )
        combination_table: list[dict[str, JsonValue]] = [
            {"fold": fold_number, "test_groups": tuple(test_groups)}
            for fold_number, test_groups in enumerate(test_combinations)
        ]
        fold_rows = [row for fold in folds for row in _role_rows(fold, source_times)]
        evidence = AnalysisResult(
            metadata=ResultMetadata(
                method="cv.combinatorial_purged_kfold",
                method_version=1,
                parameters={
                    "n_groups": self.n_groups,
                    "n_test_groups": self.n_test_groups,
                    "embargo_observations": self.embargo,
                    "max_combinations": self.max_combinations,
                    "interval_closure": "[label_start, label_end)",
                    "time_column": time,
                    "label_start_column": label_start,
                    "label_end_column": label_end,
                    "backend": "+".join(sorted(backends)),
                    "path_assignment": "ordered_group_incidence",
                    "input": diagnostics.to_parameters(),
                },
            ),
            metrics={
                "n_groups": self.n_groups,
                "n_combinations": len(folds),
                "n_paths": len(paths),
                "purged_observations": sum(len(fold.purged_indices) for fold in folds),
                "embargoed_observations": sum(len(fold.embargoed_indices) for fold in folds),
            },
            tables={
                "groups": tuple(group_table),
                "combinations": tuple(combination_table),
                "folds": tuple(fold_rows),
                "paths": tuple(path_rows),
            },
        )
        return CombinatorialSplitResult(folds=tuple(folds), paths=paths, evidence=evidence)


__all__ = [
    "CPCVPath",
    "CombinatorialPurgedKFold",
    "CombinatorialSplitResult",
    "Duration",
    "Fold",
    "PurgedKFold",
    "SplitResult",
    "WalkForward",
]
