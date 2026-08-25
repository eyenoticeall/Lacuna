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
from typing import Literal, TypeAlias

import numpy as np
import polars as pl

from lacuna._frames import eager_frame, series_time_i64
from lacuna.exceptions import DataContractError, MethodContractError
from lacuna.types import AnalysisResult, JsonValue, ResultMetadata

Duration: TypeAlias = str | int
TimeValue: TypeAlias = int | date | datetime
_DURATION_PATTERN = re.compile(r"^(?P<count>[1-9][0-9]*)(?P<unit>D|W|M|Y)$", re.IGNORECASE)


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
            times = [source_times[index] for index in indices]
            start: TimeValue | None = min(times)
            end: TimeValue | None = max(times)
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


def _reference_purge_mask(
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

            return (
                _native.interval_purge(
                    train_starts,
                    train_ends,
                    test_starts,
                    test_ends,
                ),
                "rust_native",
            )
        except (ImportError, AttributeError):
            pass
    return (
        _reference_purge_mask(train_starts, train_ends, test_starts, test_ends),
        "python_reference",
    )


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
        group_time_sets = [set(group) for group in period_groups]
        group_rows = [
            tuple(
                indexed.filter(pl.col(time).is_in(group_times)).sort([time, "_source_index"])
                .get_column("_source_index")
                .to_list()
            )
            for group_times in group_time_sets
        ]
        test_combinations = tuple(combinations(range(self.n_groups), self.n_test_groups))
        period_positions = {value: position for position, value in enumerate(unique_times)}
        folds: list[Fold] = []
        backends: set[str] = set()

        for fold_number, test_groups in enumerate(test_combinations):
            test_time_set: set[TimeValue] = set()
            for group in test_groups:
                test_time_set.update(group_time_sets[group])
            test_indices: list[int] = (
                indexed.filter(pl.col(time).is_in(test_time_set))
                .get_column("_source_index")
                .to_list()
            )
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

            embargo_times: set[TimeValue] = set()
            if self.embargo:
                for group in test_groups:
                    final_period = max(period_positions[value] for value in period_groups[group])
                    embargo_times.update(
                        unique_times[final_period + 1 : final_period + 1 + self.embargo]
                    )
                embargo_times.difference_update(test_time_set)
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

        paths = tuple(
            CPCVPath(
                path=path_index,
                fold_by_group=tuple(fold_numbers),
                test_indices=tuple(index for rows in group_rows for index in rows),
            )
            for path_index, fold_numbers in enumerate(fold_by_path)
        )
        source_times = _validated_times(indexed.sort("_source_index").get_column(time).to_list())
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
