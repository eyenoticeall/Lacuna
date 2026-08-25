"""Point-in-time joins and temporal data-correctness diagnostics."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal, TypeAlias

import numpy as np
import polars as pl

from lacuna._frames import (
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

AsOfTolerance: TypeAlias = str | int | float | timedelta
UnmatchedPolicy: TypeAlias = Literal["keep", "drop", "raise"]
RevisionMode: TypeAlias = Literal["point_in_time", "latest_only", "not_applicable", "unknown"]

_LEFT_ROW = "__lacuna_left_row"
_RIGHT_TIME = "__lacuna_right_available_time"


def _trimmed(value: str, *, name: str) -> str:
    if not value or value.strip() != value:
        raise MethodContractError(f"{name} must be a non-empty trimmed string")
    return value


def _portable_records(frame: pl.DataFrame) -> tuple[JsonValue, ...]:
    """Serialize temporal evidence without relying on the host IANA timezone database."""

    expressions: list[pl.Expr] = []
    for column, dtype in frame.schema.items():
        if isinstance(dtype, pl.Datetime) and dtype.time_zone is not None:
            expressions.append(
                pl.col(column)
                .dt.convert_time_zone("UTC")
                .dt.strftime("%+")
                .str.replace(r"\+00:00$", "Z")
                .alias(column)
            )
        elif dtype == pl.Date or isinstance(dtype, pl.Datetime | pl.Duration):
            expressions.append(pl.col(column).cast(pl.String).alias(column))
    normalized = frame.with_columns(expressions) if expressions else frame
    return frame_records(normalized)


def _by_columns(by: str | Sequence[str]) -> tuple[str, ...]:
    values = (by,) if isinstance(by, str) else tuple(by)
    if not values:
        raise MethodContractError("by must contain at least one identity column")
    for value in values:
        _trimmed(value, name="by column")
    if len(values) != len(set(values)):
        raise MethodContractError("by columns must be unique")
    return values


def _validate_revision_mode(value: RevisionMode) -> None:
    if value not in {"point_in_time", "latest_only", "not_applicable", "unknown"}:
        raise MethodContractError(
            "revision_mode must be point_in_time, latest_only, not_applicable, or unknown"
        )


def _time_unit(dtype: pl.DataType) -> str:
    if dtype == pl.Date:
        return "days"
    if isinstance(dtype, pl.Datetime | pl.Duration):
        return {
            "ns": "nanoseconds",
            "us": "microseconds",
            "ms": "milliseconds",
        }[dtype.time_unit]
    return "input_units"


def _information_ages(
    frame: pl.DataFrame,
    *,
    left_time: str,
    matched_time: str,
) -> np.ndarray[tuple[int], np.dtype[np.int64]]:
    left_values = frame.get_column(left_time).cast(pl.Int64).to_list()
    right_values = frame.get_column(matched_time).cast(pl.Int64).to_list()
    ages = [
        int(left - right)
        for left, right in zip(left_values, right_values, strict=True)
        if left is not None and right is not None
    ]
    return np.asarray(ages, dtype=np.int64)


@dataclass(frozen=True, slots=True)
class PointInTimeJoinResult:
    """A left-cardinality join table and its point-in-time evidence."""

    frame: pl.DataFrame
    evidence: AnalysisResult

    def __post_init__(self) -> None:
        if not isinstance(self.frame, pl.DataFrame):
            raise TypeError("frame must be a polars DataFrame")
        if not isinstance(self.evidence, AnalysisResult):
            raise TypeError("evidence must be an AnalysisResult")

    @property
    def metadata(self) -> ResultMetadata:
        """Expose join provenance beside the joined frame."""

        return self.evidence.metadata


def _validate_asof_inputs(
    left: pl.DataFrame,
    right: pl.DataFrame,
    *,
    left_time: str,
    right_time: str,
    by: tuple[str, ...],
    revision: str | None,
) -> int:
    if left.is_empty():
        raise DataContractError("left input must contain at least one row")
    require_no_nulls(left, [left_time, *by], name="left input")
    require_time_key(left, left_time, name="left input")
    for column in by:
        require_identifier(left, column, name="left input")
    if right.is_empty():
        if right.schema[right_time] != left.schema[left_time]:
            raise DataContractError("left and right time columns must use matching dtypes")
        return 0
    require_no_nulls(right, [right_time, *by], name="right input")
    require_time_key(right, right_time, name="right input")
    for column in by:
        require_identifier(right, column, name="right input")
        if left.schema[column] != right.schema[column]:
            raise DataContractError(f"join identity column {column!r} must use matching dtypes")
    if left.schema[left_time] != right.schema[right_time]:
        raise DataContractError("left and right time columns must use matching dtypes")

    duplicate_keys = [*by, right_time]
    duplicate_rows = int(right.select(pl.struct(duplicate_keys).is_duplicated().sum()).item())
    if duplicate_rows and revision is None:
        raise DataContractError(
            "right input has ambiguous identity/availability ties; provide revision"
        )
    if revision is not None:
        require_no_nulls(right, [revision], name="right input revisions")
        exact_keys = [*duplicate_keys, revision]
        exact_duplicates = int(right.select(pl.struct(exact_keys).is_duplicated().sum()).item())
        if exact_duplicates:
            raise DataContractError(
                "right input contains duplicate identity/availability/revision rows"
            )
    return duplicate_rows


def asof_join(
    left: object,
    right: object,
    *,
    left_time: str = "decision_time",
    right_time: str = "available_time",
    by: str | Sequence[str] = "instrument",
    effective_time: str | None = None,
    revision: str | None = None,
    revision_mode: RevisionMode = "unknown",
    tolerance: AsOfTolerance | None = None,
    allow_exact_matches: bool = True,
    unmatched: UnmatchedPolicy = "keep",
    suffix: str = "_right",
) -> PointInTimeJoinResult:
    """Join the latest record known by each decision without using future data."""

    _trimmed(left_time, name="left_time")
    _trimmed(right_time, name="right_time")
    resolved_by = _by_columns(by)
    if left_time in resolved_by or right_time in resolved_by:
        raise MethodContractError("time columns must not also be identity columns")
    if effective_time is not None:
        _trimmed(effective_time, name="effective_time")
    if revision is not None:
        _trimmed(revision, name="revision")
    _validate_revision_mode(revision_mode)
    if unmatched not in {"keep", "drop", "raise"}:
        raise MethodContractError("unmatched must be 'keep', 'drop', or 'raise'")
    _trimmed(suffix, name="suffix")
    if tolerance is not None:
        if isinstance(tolerance, bool):
            raise MethodContractError("tolerance must not be bool")
        if isinstance(tolerance, int | float) and (
            not math.isfinite(float(tolerance)) or tolerance < 0
        ):
            raise MethodContractError("numeric tolerance must be finite and non-negative")
        if isinstance(tolerance, timedelta) and tolerance < timedelta(0):
            raise MethodContractError("timedelta tolerance must be non-negative")
        if isinstance(tolerance, str):
            _trimmed(tolerance, name="tolerance")

    left_required = [left_time, *resolved_by]
    right_required = [right_time, *resolved_by]
    if effective_time is not None:
        right_required.append(effective_time)
    if revision is not None:
        right_required.append(revision)
    left_frame, left_diagnostics = eager_frame(left, required=left_required)
    right_frame, right_diagnostics = eager_frame(right, required=right_required)
    for reserved in (_LEFT_ROW, _RIGHT_TIME):
        if reserved in left_frame.columns or reserved in right_frame.columns:
            raise DataContractError(f"input contains reserved internal column {reserved!r}")
    duplicate_rows = _validate_asof_inputs(
        left_frame,
        right_frame,
        left_time=left_time,
        right_time=right_time,
        by=resolved_by,
        revision=revision,
    )
    if effective_time is not None:
        require_time_key(right_frame, effective_time, name="right input")
    output_right_time = (
        right_time if right_time not in left_frame.columns else f"{right_time}{suffix}"
    )
    if output_right_time in left_frame.columns and output_right_time != right_time:
        raise DataContractError(f"suffix produces an existing left column {output_right_time!r}")

    left_prepared = left_frame.with_row_index(_LEFT_ROW)
    right_prepared = right_frame.rename({right_time: _RIGHT_TIME})
    right_sort = [*resolved_by, _RIGHT_TIME]
    if revision is not None:
        right_sort.append(revision)
    left_sorted = left_prepared.sort([*resolved_by, left_time])
    right_sorted = right_prepared.sort(right_sort)
    join_kwargs: dict[str, object] = {
        "left_on": left_time,
        "right_on": _RIGHT_TIME,
        "by": resolved_by,
        "strategy": "backward",
        "suffix": suffix,
        "tolerance": tolerance,
        "allow_exact_matches": allow_exact_matches,
        "check_sortedness": False,
    }
    joined = left_sorted.join_asof(right_sorted, **join_kwargs)  # type: ignore[arg-type]

    potential = left_sorted.join_asof(
        right_sorted.select(*resolved_by, _RIGHT_TIME),
        left_on=left_time,
        right_on=_RIGHT_TIME,
        by=resolved_by,
        strategy="backward",
        allow_exact_matches=allow_exact_matches,
        check_sortedness=False,
    )
    final_matched = joined.get_column(_RIGHT_TIME).is_not_null()
    potential_matched = potential.get_column(_RIGHT_TIME).is_not_null()
    unmatched_count = int((~final_matched).sum())
    stale_count = int((potential_matched & ~final_matched).sum())
    if unmatched_count and unmatched == "raise":
        raise DataContractError(
            f"point-in-time join produced {unmatched_count} unmatched left rows"
        )
    if unmatched == "drop":
        joined = joined.filter(final_matched)
    joined = joined.sort(_LEFT_ROW).drop(_LEFT_ROW).rename({_RIGHT_TIME: output_right_time})
    ages = _information_ages(
        joined,
        left_time=left_time,
        matched_time=output_right_time,
    )
    if bool((ages < 0).any()):  # pragma: no cover - defensive assertion over join_asof
        raise RuntimeError("point-in-time join selected future data")

    findings: list[Finding] = []
    if unmatched_count:
        findings.append(
            Finding(
                code="BIAS_ASOF_UNMATCHED",
                title="Point-in-time join has unmatched decisions",
                message=f"{unmatched_count} left rows have no admissible right record.",
                state=FindingState.WARN,
                severity=Severity.MEDIUM,
                category="bias.availability",
                evidence={
                    "unmatched_rows": unmatched_count,
                    "stale_matches_rejected": stale_count,
                    "unmatched_policy": unmatched,
                },
            )
        )
    if revision_mode == "latest_only":
        findings.append(
            Finding(
                code="BIAS_REVISION_LATEST_ONLY",
                title="Revision history is unavailable",
                message=(
                    "The source contains only latest values and cannot establish revision safety."
                ),
                state=FindingState.UNKNOWN,
                severity=Severity.HIGH,
                category="bias.revision",
            )
        )
    elif revision_mode == "unknown":
        findings.append(
            Finding(
                code="BIAS_REVISION_STATUS_UNKNOWN",
                title="Revision status is unknown",
                message="The source revision-history status was not established.",
                state=FindingState.UNKNOWN,
                severity=Severity.MEDIUM,
                category="bias.revision",
            )
        )
    if not findings:
        findings.append(
            Finding(
                code="BIAS_ASOF_TEMPORAL_FIREWALL",
                title="Point-in-time join respects availability",
                message="Every output match is the latest admissible non-future record.",
                state=FindingState.PASS,
                severity=Severity.INFO,
                category="bias.availability",
                evidence={"matched_rows": int(ages.size)},
            )
        )

    left_diagnostics = left_diagnostics.with_execution(
        "attach_stable_left_row",
        "sort_identity_and_decision_time",
        "backward_asof_join",
        "restore_left_order",
    )
    right_diagnostics = right_diagnostics.with_execution(
        "validate_availability_and_revision_ties",
        "sort_identity_availability_revision",
    )
    evidence = AnalysisResult(
        metadata=ResultMetadata(
            method="bias.asof_join",
            method_version=1,
            parameters={
                "left_time": left_time,
                "right_time": right_time,
                "by": resolved_by,
                "effective_time": effective_time,
                "revision": revision,
                "revision_mode": revision_mode,
                "tolerance": str(tolerance) if isinstance(tolerance, timedelta) else tolerance,
                "allow_exact_matches": allow_exact_matches,
                "unmatched": unmatched,
                "suffix": suffix,
                "information_age_unit": _time_unit(left_frame.schema[left_time]),
                "left_frame": left_diagnostics.to_parameters(),
                "right_frame": right_diagnostics.to_parameters(),
            },
            input_fingerprint=fingerprint(
                {
                    "left": _portable_records(left_frame),
                    "right": _portable_records(right_frame),
                    "configuration": {
                        "left_time": left_time,
                        "right_time": right_time,
                        "by": resolved_by,
                        "effective_time": effective_time,
                        "revision": revision,
                        "revision_mode": revision_mode,
                        "tolerance": (
                            str(tolerance) if isinstance(tolerance, timedelta) else tolerance
                        ),
                        "allow_exact_matches": allow_exact_matches,
                        "unmatched": unmatched,
                    },
                },
                namespace="point-in-time-asof-join",
            ),
        ),
        metrics={
            "left_rows": left_frame.height,
            "right_rows": right_frame.height,
            "output_rows": joined.height,
            "matched_rows": int(ages.size),
            "unmatched_rows": unmatched_count,
            "stale_matches_rejected": stale_count,
            "revision_tie_rows": duplicate_rows,
            "mean_information_age": float(np.mean(ages)) if ages.size else None,
            "median_information_age": float(np.median(ages)) if ages.size else None,
            "max_information_age": int(np.max(ages)) if ages.size else None,
            "information_age_unit": _time_unit(left_frame.schema[left_time]),
            "future_matches": 0,
        },
        findings=tuple(findings),
        tables={
            "join_sample": _portable_records(joined.head(100)),
        },
        warnings=(
            "The join proves availability ordering for supplied timestamps; it does not "
            "prove source timestamps are accurate.",
        ),
    )
    return PointInTimeJoinResult(frame=joined, evidence=evidence)


def future_data_check(
    data: object,
    *,
    decision_time: str = "decision_time",
    available_time: str = "available_time",
    row_id: str | None = None,
    instrument: str | None = "instrument",
    materiality: str | None = None,
    max_examples: int = 100,
) -> AnalysisResult:
    """Count records unavailable at decision time and quantify optional materiality."""

    _trimmed(decision_time, name="decision_time")
    _trimmed(available_time, name="available_time")
    if row_id is not None:
        _trimmed(row_id, name="row_id")
    if instrument is not None:
        _trimmed(instrument, name="instrument")
    if materiality is not None:
        _trimmed(materiality, name="materiality")
    if max_examples < 0:
        raise MethodContractError("max_examples must be non-negative")
    required = [decision_time, available_time]
    for optional in (row_id, instrument, materiality):
        if optional is not None:
            required.append(optional)
    frame, diagnostics = eager_frame(data, required=required)
    if frame.is_empty():
        raise DataContractError("future-data input must contain at least one row")
    require_no_nulls(frame, [decision_time], name="future-data input")
    require_time_key(frame, decision_time, name="future-data input")
    require_time_key(frame, available_time, name="future-data input")
    if frame.schema[decision_time] != frame.schema[available_time]:
        raise DataContractError("decision_time and available_time must use matching dtypes")
    if row_id is not None:
        require_no_nulls(frame, [row_id], name="future-data input")
    if instrument is not None:
        require_identifier(frame, instrument, name="future-data input")

    missing = pl.col(available_time).is_null()
    future = pl.col(available_time) > pl.col(decision_time)
    equal = pl.col(available_time) == pl.col(decision_time)
    counts = frame.select(
        missing.sum().alias("missing"),
        future.fill_null(False).sum().alias("future"),
        equal.fill_null(False).sum().alias("equal"),
    ).row(0, named=True)
    missing_count = int(counts["missing"])
    future_count = int(counts["future"])
    equal_count = int(counts["equal"])
    materiality_total: float | None = None
    future_materiality: float | None = None
    future_materiality_fraction: float | None = None
    if materiality is not None:
        require_numeric(frame, [materiality])
        values = frame.get_column(materiality).cast(pl.Float64)
        invalid = values.is_null() | values.is_nan() | values.is_infinite()
        if bool(invalid.any()):
            raise DataContractError("materiality must contain finite non-null values")
        absolute = values.abs()
        materiality_total = float(absolute.sum())
        future_materiality = float(
            absolute.filter(frame.select(future.fill_null(False)).to_series()).sum()
        )
        future_materiality_fraction = (
            future_materiality / materiality_total if materiality_total > 0.0 else None
        )

    sample_columns = [column for column in (row_id, instrument) if column is not None]
    sample_columns.extend([decision_time, available_time])
    if materiality is not None:
        sample_columns.append(materiality)
    affected = frame.filter(future.fill_null(False)).select(sample_columns).head(max_examples)
    findings: list[Finding] = []
    if future_count:
        findings.append(
            Finding(
                code="BIAS_FUTURE_DATA",
                title="Records use future-available data",
                message=f"{future_count} rows were unavailable at their decision time.",
                state=FindingState.FAIL,
                severity=Severity.CRITICAL,
                category="bias.look_ahead",
                evidence={
                    "affected_rows": future_count,
                    "affected_fraction": future_count / frame.height,
                    "absolute_materiality": future_materiality,
                    "materiality_fraction": future_materiality_fraction,
                },
            )
        )
    if missing_count:
        findings.append(
            Finding(
                code="BIAS_AVAILABILITY_MISSING",
                title="Availability time is missing",
                message=f"{missing_count} rows cannot be classified for future-data leakage.",
                state=FindingState.UNKNOWN,
                severity=Severity.HIGH,
                category="bias.availability",
                evidence={"missing_rows": missing_count},
            )
        )
    if not findings:
        findings.append(
            Finding(
                code="BIAS_FUTURE_DATA_CLEAR",
                title="No future-available rows detected",
                message="Every supplied availability time is no later than its decision time.",
                state=FindingState.PASS,
                severity=Severity.INFO,
                category="bias.look_ahead",
                evidence={"checked_rows": frame.height},
            )
        )
    diagnostics = diagnostics.with_execution(
        "compare_availability_to_decision",
        "sample_future_rows",
        *("aggregate_absolute_materiality",) if materiality is not None else (),
    )
    return AnalysisResult(
        metadata=ResultMetadata(
            method="bias.future_data_check",
            method_version=1,
            parameters={
                "decision_time": decision_time,
                "available_time": available_time,
                "row_id": row_id,
                "instrument": instrument,
                "materiality": materiality,
                "max_examples": max_examples,
                "frame": diagnostics.to_parameters(),
            },
            input_fingerprint=fingerprint(_portable_records(frame), namespace="future-data-check"),
        ),
        metrics={
            "rows": frame.height,
            "future_rows": future_count,
            "future_fraction": future_count / frame.height,
            "missing_availability_rows": missing_count,
            "equal_boundary_rows": equal_count,
            "absolute_materiality": materiality_total,
            "future_absolute_materiality": future_materiality,
            "future_materiality_fraction": future_materiality_fraction,
        },
        findings=tuple(findings),
        tables={"future_rows": _portable_records(affected)},
    )


__all__ = [
    "AsOfTolerance",
    "PointInTimeJoinResult",
    "RevisionMode",
    "UnmatchedPolicy",
    "asof_join",
    "future_data_check",
]
