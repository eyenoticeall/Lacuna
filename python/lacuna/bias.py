"""Point-in-time joins and temporal data-correctness diagnostics."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from itertools import pairwise
from typing import Literal, TypeAlias, cast

import numpy as np
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

AsOfTolerance: TypeAlias = str | int | float | timedelta
UnmatchedPolicy: TypeAlias = Literal["keep", "drop", "raise"]
RevisionMode: TypeAlias = Literal["point_in_time", "latest_only", "not_applicable", "unknown"]
TemporalPoint: TypeAlias = date | datetime | int

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


class SurvivorshipStatus(StrEnum):
    """Strength of historical-universe evidence supplied by a source."""

    CONFIRMED_SAFE = "confirmed_safe"
    CONFIRMED_BIASED = "confirmed_biased"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class MembershipResult:
    """Active membership rows and the evidence supporting their selection."""

    frame: pl.DataFrame
    evidence: AnalysisResult

    def __post_init__(self) -> None:
        if not isinstance(self.frame, pl.DataFrame):
            raise TypeError("frame must be a polars DataFrame")
        if not isinstance(self.evidence, AnalysisResult):
            raise TypeError("evidence must be an AnalysisResult")

    @property
    def metadata(self) -> ResultMetadata:
        """Expose membership-selection provenance."""

        return self.evidence.metadata


@dataclass(frozen=True, slots=True)
class DatasetSpec:
    """Declarative semantic checks for one tabular research artifact."""

    name: str
    required: tuple[str, ...]
    keys: tuple[str, ...] = ()
    non_null: tuple[str, ...] = ()
    numeric: tuple[str, ...] = ()
    temporal: tuple[str, ...] = ()
    temporal_order: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        _trimmed(self.name, name="dataset name")
        if not self.required:
            raise MethodContractError("required must contain at least one column")
        for collection_name, values in (
            ("required", self.required),
            ("keys", self.keys),
            ("non_null", self.non_null),
            ("numeric", self.numeric),
            ("temporal", self.temporal),
        ):
            object.__setattr__(self, collection_name, tuple(values))
            for value in values:
                _trimmed(value, name=f"{collection_name} column")
            if len(values) != len(set(values)):
                raise MethodContractError(f"{collection_name} columns must be unique")
        object.__setattr__(self, "temporal_order", tuple(self.temporal_order))
        for pair in self.temporal_order:
            if len(pair) != 2:
                raise MethodContractError("temporal_order entries must contain two columns")
            _trimmed(pair[0], name="earlier temporal column")
            _trimmed(pair[1], name="later temporal column")
            if pair[0] == pair[1]:
                raise MethodContractError("temporal_order columns must be different")
        referenced = {
            *self.keys,
            *self.non_null,
            *self.numeric,
            *self.temporal,
            *(column for pair in self.temporal_order for column in pair),
        }
        if not referenced.issubset(self.required):
            raise MethodContractError(
                "all dataset checks must reference columns declared in required"
            )
        order_columns = {column for pair in self.temporal_order for column in pair}
        if not order_columns.issubset(self.temporal):
            raise MethodContractError("temporal_order columns must also be declared in temporal")

    def to_parameters(self) -> dict[str, JsonValue]:
        return {
            "name": self.name,
            "required": self.required,
            "keys": self.keys,
            "non_null": self.non_null,
            "numeric": self.numeric,
            "temporal": self.temporal,
            "temporal_order": self.temporal_order,
        }


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


def revision_diagnostics(
    data: object,
    *,
    entity: str | Sequence[str] = "instrument",
    effective_time: str = "effective_time",
    available_time: str = "available_time",
    revision: str | None = "revision_id",
    value: str | None = None,
    source_mode: RevisionMode = "unknown",
) -> AnalysisResult:
    """Validate version identity and publication ordering within revised facts."""

    entities = _by_columns(entity)
    _trimmed(effective_time, name="effective_time")
    _trimmed(available_time, name="available_time")
    if revision is not None:
        _trimmed(revision, name="revision")
    if value is not None:
        _trimmed(value, name="value")
    _validate_revision_mode(source_mode)
    if source_mode == "not_applicable":
        raise MethodContractError("revision diagnostics cannot use source_mode='not_applicable'")
    if source_mode == "point_in_time" and revision is None:
        raise MethodContractError("point_in_time revision sources require a revision column")
    required = [*entities, effective_time, available_time]
    if revision is not None:
        required.append(revision)
    if value is not None:
        required.append(value)
    frame, diagnostics = eager_frame(data, required=required)
    if frame.is_empty():
        raise DataContractError("revision source must contain at least one row")
    require_no_nulls(frame, [*entities, effective_time, available_time], name="revision source")
    for column in entities:
        require_identifier(frame, column, name="revision source")
    require_time_key(frame, effective_time, name="revision source")
    require_time_key(frame, available_time, name="revision source")
    if revision is not None:
        require_no_nulls(frame, [revision], name="revision source")
        revision_dtype = frame.schema[revision]
        if not (
            revision_dtype.is_integer()
            or revision_dtype == pl.String
            or revision_dtype == pl.Categorical
            or isinstance(revision_dtype, pl.Enum | pl.Datetime)
            or revision_dtype == pl.Date
        ):
            raise DataContractError(
                "revision must be an ordered integer, string, categorical, date, or datetime"
            )

    fact_keys = [*entities, effective_time]
    version_keys = [*fact_keys, revision] if revision is not None else [*fact_keys, available_time]
    duplicate_versions = int(frame.select(pl.struct(version_keys).is_duplicated().sum()).item())
    if duplicate_versions:
        raise DataContractError("revision source contains duplicate version identities")
    if revision is None:
        ordered = frame.sort([*fact_keys, available_time])
        order_violations = 0
    else:
        ordered = frame.sort([*fact_keys, revision])
        prior_available = pl.col(available_time).shift(1).over(fact_keys)
        order_violations = int(
            ordered.select(
                (prior_available.is_not_null() & (pl.col(available_time) < prior_available))
                .sum()
                .alias("violations")
            ).item()
        )
    aggregations: list[pl.Expr] = [
        pl.len().alias("version_count"),
        pl.col(available_time).min().alias("first_available_time"),
        pl.col(available_time).max().alias("last_available_time"),
    ]
    if value is not None:
        aggregations.append(pl.col(value).n_unique().alias("distinct_value_count"))
    facts = ordered.group_by(fact_keys, maintain_order=True).agg(aggregations)
    revised_facts = int(facts.select((pl.col("version_count") > 1).sum()).item())
    maximum_versions = cast(int, facts.get_column("version_count").max())
    findings: list[Finding] = []
    if order_violations:
        findings.append(
            Finding(
                code="BIAS_REVISION_ORDER_INVALID",
                title="Revision publication order is inconsistent",
                message=(
                    f"{order_violations} versions become available earlier than a lower "
                    "declared revision."
                ),
                state=FindingState.FAIL,
                severity=Severity.HIGH,
                category="bias.revision",
                evidence={"order_violations": order_violations},
            )
        )
    if source_mode == "latest_only":
        findings.append(
            Finding(
                code="BIAS_REVISION_LATEST_ONLY",
                title="Only latest revisions are available",
                message="Historical values cannot be reconstructed at prior decision times.",
                state=FindingState.UNKNOWN,
                severity=Severity.HIGH,
                category="bias.revision",
            )
        )
    elif source_mode == "unknown":
        findings.append(
            Finding(
                code="BIAS_REVISION_STATUS_UNKNOWN",
                title="Revision coverage is unknown",
                message="The source has not established complete historical revision coverage.",
                state=FindingState.UNKNOWN,
                severity=Severity.HIGH,
                category="bias.revision",
            )
        )
    elif not order_violations:
        findings.append(
            Finding(
                code="BIAS_REVISION_HISTORY_VALID",
                title="Revision history is structurally valid",
                message="Version identities are unique and availability follows revision order.",
                state=FindingState.PASS,
                severity=Severity.INFO,
                category="bias.revision",
                evidence={"revised_facts": revised_facts},
            )
        )
    diagnostics = diagnostics.with_execution(
        "group_fact_versions",
        "validate_revision_availability_order",
    )
    return AnalysisResult(
        metadata=ResultMetadata(
            method="bias.revision_diagnostics",
            method_version=1,
            parameters={
                "entity": entities,
                "effective_time": effective_time,
                "available_time": available_time,
                "revision": revision,
                "value": value,
                "source_mode": source_mode,
                "frame": diagnostics.to_parameters(),
            },
            input_fingerprint=fingerprint(
                _portable_records(frame), namespace="revision-diagnostics"
            ),
        ),
        metrics={
            "rows": frame.height,
            "fact_count": facts.height,
            "revised_facts": revised_facts,
            "revision_fraction": revised_facts / facts.height,
            "maximum_versions_per_fact": maximum_versions,
            "order_violations": order_violations,
            "source_mode": source_mode,
        },
        findings=tuple(findings),
        tables={"facts": _portable_records(facts)},
        warnings=(
            "Structural revision checks cannot prove that a vendor supplied every "
            "historical version.",
        ),
    )


def _resolve_survivorship_status(
    value: SurvivorshipStatus | str,
) -> SurvivorshipStatus:
    try:
        return SurvivorshipStatus(value)
    except ValueError as error:
        raise MethodContractError(
            "source_status must be confirmed_safe, confirmed_biased, or unknown"
        ) from error


def _membership_interval_issues(
    frame: pl.DataFrame,
    *,
    by: Sequence[str],
    valid_from: str,
    valid_to: str,
) -> tuple[int, int]:
    invalid = int(
        frame.select(
            (pl.col(valid_to).is_not_null() & (pl.col(valid_from) >= pl.col(valid_to))).sum()
        ).item()
    )
    ordered = frame.sort([*by, valid_from])
    prior_max_end = pl.col(valid_to).cum_max().shift(1).over(by)
    prior_open = pl.col(valid_to).is_null().cum_max().shift(1).over(by).fill_null(False)
    overlap = prior_open | (prior_max_end.is_not_null() & (pl.col(valid_from) < prior_max_end))
    overlaps = int(ordered.select(overlap.sum()).item())
    return invalid, overlaps


def _validate_membership_frame(
    data: object,
    *,
    identity: tuple[str, ...],
    valid_from: str,
    valid_to: str,
    available_time: str,
) -> tuple[pl.DataFrame, FrameDiagnostics]:
    required = [*identity, valid_from, valid_to, available_time]
    frame, diagnostics = eager_frame(data, required=required)
    if frame.is_empty():
        raise DataContractError("membership source must contain at least one row")
    require_no_nulls(frame, [*identity, valid_from], name="membership source")
    for column in identity:
        require_identifier(frame, column, name="membership source")
    require_time_key(frame, valid_from, name="membership source")
    expected = frame.schema[valid_from]
    null_temporal = [
        column for column in (valid_to, available_time) if frame.schema[column] == pl.Null
    ]
    if null_temporal:
        frame = frame.with_columns(
            pl.col(column).cast(expected).alias(column) for column in null_temporal
        )
    for column in (valid_to, available_time):
        require_time_key(frame, column, name="membership source")
    mismatched = [
        column for column in (valid_to, available_time) if frame.schema[column] != expected
    ]
    if mismatched:
        details = ", ".join(f"{column}={frame.schema[column]}" for column in mismatched)
        raise DataContractError(
            "membership temporal columns must use matching dtypes: "
            f"{valid_from}={expected}, {details}"
        )
    return frame, diagnostics


def survivorship_diagnostics(
    data: object,
    *,
    identity: str | Sequence[str] = ("index", "instrument"),
    valid_from: str = "valid_from",
    valid_to: str = "valid_to",
    available_time: str = "available_time",
    delisted: str | None = None,
    source_status: SurvivorshipStatus | str = SurvivorshipStatus.UNKNOWN,
    includes_delisted: bool | None = None,
) -> AnalysisResult:
    """Assess interval integrity and the declared strength of survivorship evidence."""

    identities = _by_columns(identity)
    status = _resolve_survivorship_status(source_status)
    for value, name in (
        (valid_from, "valid_from"),
        (valid_to, "valid_to"),
        (available_time, "available_time"),
    ):
        _trimmed(value, name=name)
    if delisted is not None:
        _trimmed(delisted, name="delisted")
    if status is SurvivorshipStatus.CONFIRMED_SAFE and (
        delisted is None or includes_delisted is not True
    ):
        raise MethodContractError(
            "confirmed_safe requires a delisted column and includes_delisted=True"
        )

    frame, diagnostics = _validate_membership_frame(
        data,
        identity=identities,
        valid_from=valid_from,
        valid_to=valid_to,
        available_time=available_time,
    )
    if delisted is not None:
        if delisted not in frame.columns:
            raise DataContractError(f"missing required columns: {delisted}")
        if frame.schema[delisted] != pl.Boolean:
            raise DataContractError("delisted must use a Boolean dtype")

    invalid_intervals, overlapping_intervals = _membership_interval_issues(
        frame,
        by=identities,
        valid_from=valid_from,
        valid_to=valid_to,
    )
    missing_availability = frame.get_column(available_time).null_count()
    late_availability = int(
        frame.select(
            (
                pl.col(available_time).is_not_null() & (pl.col(available_time) > pl.col(valid_from))
            ).sum()
        ).item()
    )
    delisted_rows = (
        int(frame.select(pl.col(delisted).fill_null(False).sum()).item())
        if delisted is not None
        else None
    )
    findings: list[Finding] = []
    if invalid_intervals:
        findings.append(
            Finding(
                code="BIAS_MEMBERSHIP_INTERVAL_INVALID",
                title="Membership intervals are invalid",
                message=f"{invalid_intervals} rows do not satisfy valid_from < valid_to.",
                state=FindingState.FAIL,
                severity=Severity.HIGH,
                category="bias.survivorship",
                evidence={"invalid_intervals": invalid_intervals},
            )
        )
    if overlapping_intervals:
        findings.append(
            Finding(
                code="BIAS_MEMBERSHIP_INTERVAL_OVERLAP",
                title="Membership intervals overlap",
                message=(
                    f"{overlapping_intervals} rows overlap an earlier interval for the "
                    "same membership identity."
                ),
                state=FindingState.FAIL,
                severity=Severity.HIGH,
                category="bias.survivorship",
                evidence={"overlapping_intervals": overlapping_intervals},
            )
        )
    if late_availability:
        findings.append(
            Finding(
                code="BIAS_MEMBERSHIP_LATE_AVAILABILITY",
                title="Membership begins before it is observable",
                message=f"{late_availability} intervals become known after their start.",
                state=FindingState.FAIL,
                severity=Severity.HIGH,
                category="bias.availability",
                evidence={"late_availability_rows": late_availability},
            )
        )
    if missing_availability:
        findings.append(
            Finding(
                code="BIAS_MEMBERSHIP_AVAILABILITY_UNKNOWN",
                title="Membership availability is incomplete",
                message=f"{missing_availability} rows have no availability timestamp.",
                state=FindingState.UNKNOWN,
                severity=Severity.HIGH,
                category="bias.availability",
                evidence={"missing_availability_rows": missing_availability},
            )
        )

    structural_failure = bool(invalid_intervals or overlapping_intervals or late_availability)
    if status is SurvivorshipStatus.CONFIRMED_BIASED:
        findings.append(
            Finding(
                code="BIAS_SURVIVORSHIP_CONFIRMED",
                title="Source is confirmed survivorship-biased",
                message=(
                    "The declared source filters the historical universe using future survival."
                ),
                state=FindingState.FAIL,
                severity=Severity.CRITICAL,
                category="bias.survivorship",
            )
        )
    elif status is SurvivorshipStatus.UNKNOWN:
        findings.append(
            Finding(
                code="BIAS_SURVIVORSHIP_UNKNOWN",
                title="Survivorship handling is unknown",
                message=(
                    "The source has not established historical membership and delisting coverage."
                ),
                state=FindingState.UNKNOWN,
                severity=Severity.HIGH,
                category="bias.survivorship",
            )
        )
    elif not structural_failure and not missing_availability:
        findings.append(
            Finding(
                code="BIAS_SURVIVORSHIP_SAFE",
                title="Survivorship evidence is structurally complete",
                message=(
                    "Historical intervals, availability, and declared delistings are represented."
                ),
                state=FindingState.PASS,
                severity=Severity.INFO,
                category="bias.survivorship",
                evidence={"delisted_rows": delisted_rows},
            )
        )

    diagnostics = diagnostics.with_execution(
        "validate_half_open_intervals",
        "validate_membership_availability",
        "assess_survivorship_declaration",
    )
    return AnalysisResult(
        metadata=ResultMetadata(
            method="bias.survivorship_diagnostics",
            method_version=1,
            parameters={
                "identity": identities,
                "valid_from": valid_from,
                "valid_to": valid_to,
                "available_time": available_time,
                "delisted": delisted,
                "source_status": status,
                "includes_delisted": includes_delisted,
                "frame": diagnostics.to_parameters(),
            },
            input_fingerprint=fingerprint(
                _portable_records(frame), namespace="survivorship-diagnostics"
            ),
        ),
        metrics={
            "rows": frame.height,
            "membership_identities": frame.select(pl.struct(identities).n_unique()).item(),
            "invalid_intervals": invalid_intervals,
            "overlapping_intervals": overlapping_intervals,
            "missing_availability_rows": missing_availability,
            "late_availability_rows": late_availability,
            "delisted_rows": delisted_rows,
            "source_status": status,
            "includes_delisted": includes_delisted,
        },
        findings=tuple(findings),
        warnings=(
            "A structurally valid source declaration does not independently verify vendor "
            "completeness.",
        ),
    )


def membership_at(
    data: object,
    *,
    as_of: TemporalPoint,
    identity: str | Sequence[str] = ("index", "instrument"),
    valid_from: str = "valid_from",
    valid_to: str = "valid_to",
    available_time: str = "available_time",
    source_status: SurvivorshipStatus | str = SurvivorshipStatus.UNKNOWN,
) -> MembershipResult:
    """Select observable members active at one instant using half-open intervals."""

    identities = _by_columns(identity)
    status = _resolve_survivorship_status(source_status)
    frame, diagnostics = _validate_membership_frame(
        data,
        identity=identities,
        valid_from=valid_from,
        valid_to=valid_to,
        available_time=available_time,
    )
    invalid, overlaps = _membership_interval_issues(
        frame,
        by=identities,
        valid_from=valid_from,
        valid_to=valid_to,
    )
    if invalid or overlaps:
        raise DataContractError(
            "membership selection requires valid non-overlapping half-open intervals; "
            f"invalid={invalid}, overlapping={overlaps}"
        )
    try:
        boundary = pl.Series("as_of", [as_of], dtype=frame.schema[valid_from]).item()
    except (TypeError, ValueError, OverflowError) as error:
        raise MethodContractError(
            f"as_of must be representable as {frame.schema[valid_from]}"
        ) from error
    active = (pl.col(valid_from) <= pl.lit(boundary)) & (
        pl.col(valid_to).is_null() | (pl.lit(boundary) < pl.col(valid_to))
    )
    observable = pl.col(available_time).is_not_null() & (pl.col(available_time) <= pl.lit(boundary))
    active_candidates = frame.filter(active)
    selected = active_candidates.filter(observable).sort(list(identities))
    future_known = active_candidates.filter(~observable)
    duplicate_active = int(selected.select(pl.struct(identities).is_duplicated().sum()).item())
    if duplicate_active:
        raise DataContractError(
            f"membership selection produced {duplicate_active} duplicate active identities"
        )
    findings: list[Finding] = []
    if future_known.height:
        findings.append(
            Finding(
                code="BIAS_MEMBERSHIP_NOT_YET_AVAILABLE",
                title="Active memberships were not yet observable",
                message=(
                    f"{future_known.height} otherwise-active rows were excluded by the "
                    "availability firewall."
                ),
                state=FindingState.WARN,
                severity=Severity.HIGH,
                category="bias.availability",
                evidence={"excluded_rows": future_known.height},
            )
        )
    if status is SurvivorshipStatus.CONFIRMED_BIASED:
        findings.append(
            Finding(
                code="BIAS_SURVIVORSHIP_CONFIRMED",
                title="Source is confirmed survivorship-biased",
                message="Selected membership rows come from a source declared future-filtered.",
                state=FindingState.FAIL,
                severity=Severity.CRITICAL,
                category="bias.survivorship",
            )
        )
    elif status is SurvivorshipStatus.UNKNOWN:
        findings.append(
            Finding(
                code="BIAS_SURVIVORSHIP_UNKNOWN",
                title="Survivorship handling is unknown",
                message=(
                    "Selection is time-filtered, but historical universe completeness is unknown."
                ),
                state=FindingState.UNKNOWN,
                severity=Severity.HIGH,
                category="bias.survivorship",
            )
        )
    elif not findings:
        findings.append(
            Finding(
                code="BIAS_MEMBERSHIP_POINT_IN_TIME",
                title="Membership selection is point-in-time safe",
                message="All selected memberships were active and observable at the boundary.",
                state=FindingState.PASS,
                severity=Severity.INFO,
                category="bias.survivorship",
            )
        )
    diagnostics = diagnostics.with_execution(
        "validate_half_open_intervals",
        "filter_active_intervals",
        "apply_availability_firewall",
    )
    boundary_record = _portable_records(
        pl.DataFrame({"as_of": pl.Series([boundary], dtype=frame.schema[valid_from])})
    )[0]
    return MembershipResult(
        frame=selected,
        evidence=AnalysisResult(
            metadata=ResultMetadata(
                method="bias.membership_at",
                method_version=1,
                parameters={
                    "as_of": boundary_record,
                    "identity": identities,
                    "valid_from": valid_from,
                    "valid_to": valid_to,
                    "available_time": available_time,
                    "source_status": status,
                    "frame": diagnostics.to_parameters(),
                },
                input_fingerprint=fingerprint(_portable_records(frame), namespace="membership-at"),
            ),
            metrics={
                "source_rows": frame.height,
                "active_candidate_rows": active_candidates.height,
                "selected_rows": selected.height,
                "not_yet_available_rows": future_known.height,
                "source_status": status,
            },
            findings=tuple(findings),
            tables={"excluded_active_rows": _portable_records(future_known)},
        ),
    )


def universe_drift(
    data: object,
    *,
    snapshot_time: str = "snapshot_time",
    instrument: str = "instrument",
    universe: str | None = None,
    source_status: SurvivorshipStatus | str = SurvivorshipStatus.UNKNOWN,
    warning_threshold: float = 0.5,
) -> AnalysisResult:
    """Measure consecutive universe additions, removals, and Jaccard drift."""

    _trimmed(snapshot_time, name="snapshot_time")
    _trimmed(instrument, name="instrument")
    if universe is not None:
        _trimmed(universe, name="universe")
    if not math.isfinite(warning_threshold) or not 0 <= warning_threshold <= 1:
        raise MethodContractError("warning_threshold must be finite and between zero and one")
    status = _resolve_survivorship_status(source_status)
    required = [snapshot_time, instrument, *([universe] if universe is not None else [])]
    frame, diagnostics = eager_frame(data, required=required)
    if frame.is_empty():
        raise DataContractError("universe snapshots must contain at least one row")
    require_no_nulls(frame, required, name="universe snapshots")
    require_time_key(frame, snapshot_time, name="universe snapshots")
    require_identifier(frame, instrument, name="universe snapshots")
    if universe is not None:
        require_identifier(frame, universe, name="universe snapshots")
    keys = [*([universe] if universe is not None else []), snapshot_time, instrument]
    duplicates = int(frame.select(pl.struct(keys).is_duplicated().sum()).item())
    if duplicates:
        raise DataContractError(
            f"universe snapshots contain {duplicates} duplicate membership rows"
        )

    group_columns = [universe] if universe is not None else []
    partitions = (
        frame.partition_by(group_columns, as_dict=True, maintain_order=True)
        if group_columns
        else {(): frame}
    )
    transitions: list[dict[str, object]] = []
    for group_key, group in partitions.items():
        snapshots = group.sort(snapshot_time).partition_by(
            snapshot_time, as_dict=True, maintain_order=True
        )
        ordered = list(snapshots.items())
        for (previous_key, previous), (current_key, current) in pairwise(ordered):
            previous_members = set(previous.get_column(instrument).to_list())
            current_members = set(current.get_column(instrument).to_list())
            union = previous_members | current_members
            retained = previous_members & current_members
            previous_value = previous_key[0] if isinstance(previous_key, tuple) else previous_key
            current_value = current_key[0] if isinstance(current_key, tuple) else current_key
            record: dict[str, object] = {
                "previous_time": previous_value,
                "current_time": current_value,
                "previous_size": len(previous_members),
                "current_size": len(current_members),
                "additions": len(current_members - previous_members),
                "removals": len(previous_members - current_members),
                "retained": len(retained),
                "retention": len(retained) / len(previous_members),
                "jaccard": len(retained) / len(union),
                "drift": 1.0 - (len(retained) / len(union)),
            }
            if universe is not None:
                record[universe] = group_key[0] if isinstance(group_key, tuple) else group_key
            transitions.append(record)
    transition_frame = pl.DataFrame(transitions) if transitions else pl.DataFrame()
    drift_values = transition_frame.get_column("drift").to_list() if transitions else []
    high_drift = sum(float(value) >= warning_threshold for value in drift_values)
    findings: list[Finding] = []
    if high_drift:
        findings.append(
            Finding(
                code="BIAS_UNIVERSE_DRIFT_HIGH",
                title="Universe composition changes materially",
                message=f"{high_drift} transitions meet the configured drift threshold.",
                state=FindingState.WARN,
                severity=Severity.MEDIUM,
                category="bias.universe",
                evidence={
                    "high_drift_transitions": high_drift,
                    "warning_threshold": warning_threshold,
                },
            )
        )
    if status is SurvivorshipStatus.CONFIRMED_BIASED:
        findings.append(
            Finding(
                code="BIAS_SURVIVORSHIP_CONFIRMED",
                title="Universe source is confirmed survivorship-biased",
                message=(
                    "Drift measurements do not make a future-filtered source historically safe."
                ),
                state=FindingState.FAIL,
                severity=Severity.CRITICAL,
                category="bias.survivorship",
            )
        )
    elif status is SurvivorshipStatus.UNKNOWN:
        findings.append(
            Finding(
                code="BIAS_SURVIVORSHIP_UNKNOWN",
                title="Universe source survivorship is unknown",
                message=(
                    "Composition drift is measured, but historical source completeness is unknown."
                ),
                state=FindingState.UNKNOWN,
                severity=Severity.HIGH,
                category="bias.survivorship",
            )
        )
    elif not findings:
        findings.append(
            Finding(
                code="BIAS_UNIVERSE_DRIFT_MEASURED",
                title="Universe drift is measured",
                message="Consecutive snapshot composition changes are below the warning threshold.",
                state=FindingState.PASS,
                severity=Severity.INFO,
                category="bias.universe",
            )
        )
    unique_snapshots = frame.select(pl.struct([*group_columns, snapshot_time]).n_unique()).item()
    diagnostics = diagnostics.with_execution(
        "group_snapshot_members",
        "compare_consecutive_snapshots",
    )
    return AnalysisResult(
        metadata=ResultMetadata(
            method="bias.universe_drift",
            method_version=1,
            parameters={
                "snapshot_time": snapshot_time,
                "instrument": instrument,
                "universe": universe,
                "source_status": status,
                "warning_threshold": warning_threshold,
                "frame": diagnostics.to_parameters(),
            },
            input_fingerprint=fingerprint(_portable_records(frame), namespace="universe-drift"),
        ),
        metrics={
            "rows": frame.height,
            "snapshots": unique_snapshots,
            "transitions": len(transitions),
            "mean_drift": float(np.mean(drift_values)) if drift_values else 0.0,
            "maximum_drift": max(drift_values, default=0.0),
            "high_drift_transitions": high_drift,
            "source_status": status,
        },
        findings=tuple(findings),
        tables={
            "transitions": _portable_records(transition_frame) if transitions else (),
        },
    )


def validate_dataset(data: object, *, spec: DatasetSpec) -> AnalysisResult:
    """Validate a table against a declarative structural and temporal contract."""

    if not isinstance(spec, DatasetSpec):
        raise TypeError("spec must be a DatasetSpec")
    frame, diagnostics = eager_frame(data)
    missing = tuple(column for column in spec.required if column not in frame.columns)
    present = tuple(column for column in spec.required if column in frame.columns)
    findings: list[Finding] = []
    if missing:
        findings.append(
            Finding(
                code="DATASET_REQUIRED_COLUMNS_MISSING",
                title="Required dataset columns are missing",
                message=f"{len(missing)} required columns are absent.",
                state=FindingState.FAIL,
                severity=Severity.HIGH,
                category="data.schema",
                evidence={"missing_columns": missing},
            )
        )
    if not frame.height:
        findings.append(
            Finding(
                code="DATASET_EMPTY",
                title="Dataset is empty",
                message="The dataset contains no rows to validate.",
                state=FindingState.FAIL,
                severity=Severity.HIGH,
                category="data.schema",
            )
        )

    checked_non_null = [column for column in spec.non_null if column in frame.columns]
    null_counts = {
        column: frame.get_column(column).null_count()
        for column in checked_non_null
        if frame.get_column(column).null_count()
    }
    if null_counts:
        findings.append(
            Finding(
                code="DATASET_NULL_CONSTRAINT_FAILED",
                title="Required non-null values are missing",
                message=f"{sum(null_counts.values())} null values violate the dataset contract.",
                state=FindingState.FAIL,
                severity=Severity.HIGH,
                category="data.quality",
                evidence={"null_counts": null_counts},
            )
        )
    checked_keys = [column for column in spec.keys if column in frame.columns]
    duplicate_rows = (
        int(frame.select(pl.struct(checked_keys).is_duplicated().sum()).item())
        if len(checked_keys) == len(spec.keys) and checked_keys
        else 0
    )
    if duplicate_rows:
        findings.append(
            Finding(
                code="DATASET_KEY_NOT_UNIQUE",
                title="Dataset keys are not unique",
                message=f"{duplicate_rows} rows share a declared logical key.",
                state=FindingState.FAIL,
                severity=Severity.HIGH,
                category="data.quality",
                evidence={"duplicate_rows": duplicate_rows, "keys": spec.keys},
            )
        )

    invalid_numeric: dict[str, str] = {}
    nonfinite_counts: dict[str, int] = {}
    for column in spec.numeric:
        if column not in frame.columns:
            continue
        dtype = frame.schema[column]
        if not dtype.is_numeric():
            invalid_numeric[column] = str(dtype)
            continue
        count = int(frame.select((~pl.col(column).cast(pl.Float64).is_finite()).sum()).item())
        if count:
            nonfinite_counts[column] = count
    if invalid_numeric:
        findings.append(
            Finding(
                code="DATASET_NUMERIC_DTYPE_INVALID",
                title="Numeric columns have invalid dtypes",
                message=f"{len(invalid_numeric)} declared numeric columns are not numeric.",
                state=FindingState.FAIL,
                severity=Severity.HIGH,
                category="data.schema",
                evidence={"invalid_dtypes": invalid_numeric},
            )
        )
    if nonfinite_counts:
        findings.append(
            Finding(
                code="DATASET_NONFINITE_VALUES",
                title="Numeric columns contain non-finite values",
                message=f"{sum(nonfinite_counts.values())} values are NaN or infinite.",
                state=FindingState.FAIL,
                severity=Severity.HIGH,
                category="data.quality",
                evidence={"nonfinite_counts": nonfinite_counts},
            )
        )

    invalid_temporal: dict[str, str] = {}
    for column in spec.temporal:
        if column not in frame.columns:
            continue
        try:
            require_time_key(frame, column, name=spec.name)
        except DataContractError:
            invalid_temporal[column] = str(frame.schema[column])
    if invalid_temporal:
        findings.append(
            Finding(
                code="DATASET_TEMPORAL_DTYPE_INVALID",
                title="Temporal columns have invalid dtypes",
                message=f"{len(invalid_temporal)} temporal columns are not ordered time keys.",
                state=FindingState.FAIL,
                severity=Severity.HIGH,
                category="data.schema",
                evidence={"invalid_dtypes": invalid_temporal},
            )
        )
    order_violations: dict[str, int] = {}
    for earlier, later in spec.temporal_order:
        if earlier not in frame.columns or later not in frame.columns:
            continue
        if earlier in invalid_temporal or later in invalid_temporal:
            continue
        if frame.schema[earlier] != frame.schema[later]:
            order_violations[f"{earlier}<={later}:dtype_mismatch"] = frame.height
            continue
        count = int(
            frame.select(
                (
                    pl.col(earlier).is_not_null()
                    & pl.col(later).is_not_null()
                    & (pl.col(earlier) > pl.col(later))
                ).sum()
            ).item()
        )
        if count:
            order_violations[f"{earlier}<={later}"] = count
    if order_violations:
        findings.append(
            Finding(
                code="DATASET_TEMPORAL_ORDER_INVALID",
                title="Temporal ordering constraints are violated",
                message=f"{sum(order_violations.values())} rows violate temporal order.",
                state=FindingState.FAIL,
                severity=Severity.HIGH,
                category="data.quality",
                evidence={"violations": order_violations},
            )
        )
    if not findings:
        findings.append(
            Finding(
                code="DATASET_CONTRACT_VALID",
                title="Dataset contract is valid",
                message="All declared schema, key, numeric, and temporal checks pass.",
                state=FindingState.PASS,
                severity=Severity.INFO,
                category="data.quality",
            )
        )
    diagnostics = diagnostics.with_execution(
        "check_required_columns",
        "check_null_and_key_constraints",
        "check_numeric_values",
        "check_temporal_constraints",
    )
    return AnalysisResult(
        metadata=ResultMetadata(
            method="bias.validate_dataset",
            method_version=1,
            parameters={"spec": spec.to_parameters(), "frame": diagnostics.to_parameters()},
            input_fingerprint=fingerprint(_portable_records(frame), namespace="dataset-validation"),
        ),
        metrics={
            "rows": frame.height,
            "columns": frame.width,
            "required_columns": len(spec.required),
            "present_required_columns": len(present),
            "missing_required_columns": len(missing),
            "duplicate_key_rows": duplicate_rows,
            "null_constraint_violations": sum(null_counts.values()),
            "nonfinite_values": sum(nonfinite_counts.values()),
            "temporal_order_violations": sum(order_violations.values()),
        },
        findings=tuple(findings),
    )


__all__ = [
    "AsOfTolerance",
    "DatasetSpec",
    "MembershipResult",
    "PointInTimeJoinResult",
    "RevisionMode",
    "SurvivorshipStatus",
    "UnmatchedPolicy",
    "asof_join",
    "future_data_check",
    "membership_at",
    "revision_diagnostics",
    "survivorship_diagnostics",
    "universe_drift",
    "validate_dataset",
]
