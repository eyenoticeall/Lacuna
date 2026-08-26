"""Deterministic signal transformations with structured evidence."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from types import MappingProxyType
from typing import Literal, TypeAlias

import numpy as np
import numpy.typing as npt
import polars as pl

from lacuna._attrition import attrition_record
from lacuna._frames import (
    FrameDiagnostics,
    eager_frame,
    frame_records,
    paired_numeric_policy,
    require_compatible_keys,
    require_no_nulls,
    require_numeric,
    require_unique,
    validate_panel_schema,
)
from lacuna.exceptions import DataContractError, MethodContractError
from lacuna.types import AnalysisResult, Finding, FindingState, JsonValue, ResultMetadata, Severity

BucketKind = Literal["quantile", "equal_width", "edges", "threshold"]
TiePolicy = Literal["balanced", "preserve"]
OutOfRangePolicy = Literal["raise", "drop"]
EqualToPolicy = Literal["lower", "upper"]
SmallGroupPolicy = Literal["raise", "drop"]
FloatArray: TypeAlias = npt.NDArray[np.float64]


def _finite(value: object, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise MethodContractError(f"{name} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise MethodContractError(f"{name} must be a finite number")
    return result


def _boundaries(values: Sequence[float], *, name: str) -> tuple[float, ...]:
    normalized = tuple(_finite(value, name=name) for value in values)
    if len(normalized) < 3:
        raise MethodContractError(f"{name} must contain at least three boundaries")
    if any(right <= left for left, right in pairwise(normalized)):
        raise MethodContractError(f"{name} must be strictly increasing")
    return normalized


@dataclass(frozen=True, slots=True)
class BucketSpec:
    """Validated, immutable signal-bucket assignment policy."""

    kind: BucketKind
    count: int | None = None
    boundaries: tuple[float, ...] = ()
    tie_policy: TiePolicy = "balanced"
    split_at: float | None = None
    equal_to: EqualToPolicy = "upper"
    out_of_range: OutOfRangePolicy = "raise"

    def __post_init__(self) -> None:
        if self.kind not in {"quantile", "equal_width", "edges", "threshold"}:
            raise MethodContractError(f"unsupported bucket kind: {self.kind!r}")
        if self.tie_policy not in {"balanced", "preserve"}:
            raise MethodContractError("tie_policy must be 'balanced' or 'preserve'")
        if self.equal_to not in {"lower", "upper"}:
            raise MethodContractError("equal_to must be 'lower' or 'upper'")
        if self.out_of_range not in {"raise", "drop"}:
            raise MethodContractError("out_of_range must be 'raise' or 'drop'")
        if self.count is not None and (
            isinstance(self.count, bool) or not isinstance(self.count, int) or self.count < 2
        ):
            raise MethodContractError("bucket count must be an integer of at least 2")
        if self.kind in {"quantile", "equal_width"} and self.count is None:
            raise MethodContractError(f"{self.kind} buckets require count")
        if self.kind == "quantile":
            if self.boundaries:
                normalized = _boundaries(self.boundaries, name="quantile boundaries")
                if normalized[0] != 0.0 or normalized[-1] != 1.0:
                    raise MethodContractError("quantile boundaries must begin at 0 and end at 1")
                object.__setattr__(self, "boundaries", normalized)
                object.__setattr__(self, "count", len(normalized) - 1)
            if self.split_at is not None:
                object.__setattr__(self, "split_at", _finite(self.split_at, name="split_at"))
                if self.boundaries:
                    raise MethodContractError(
                        "split-aware quantiles cannot use custom quantile boundaries"
                    )
        elif self.kind == "edges":
            normalized = _boundaries(self.boundaries, name="numeric edges")
            object.__setattr__(self, "boundaries", normalized)
            object.__setattr__(self, "count", len(normalized) - 1)
            if self.split_at is not None:
                raise MethodContractError("numeric edge buckets do not accept split_at")
        elif self.kind == "threshold":
            if self.split_at is None:
                raise MethodContractError("threshold buckets require a threshold value")
            object.__setattr__(self, "split_at", _finite(self.split_at, name="threshold"))
            object.__setattr__(self, "count", 2)
            if self.boundaries:
                raise MethodContractError("threshold buckets do not accept boundaries")
        else:
            if self.boundaries or self.split_at is not None:
                raise MethodContractError(
                    "equal-width buckets accept count but not boundaries or split_at"
                )

    @classmethod
    def quantiles(
        cls,
        count: int = 10,
        *,
        edges: Sequence[float] | None = None,
        tie_policy: TiePolicy = "balanced",
        split_at: float | None = None,
        equal_to: EqualToPolicy = "upper",
    ) -> BucketSpec:
        """Create count- or probability-edge-based quantile buckets."""

        return cls(
            "quantile",
            count=count,
            boundaries=tuple(edges or ()),
            tie_policy=tie_policy,
            split_at=split_at,
            equal_to=equal_to,
        )

    @classmethod
    def equal_width(cls, count: int) -> BucketSpec:
        """Create equal-width buckets within each declared group."""

        return cls("equal_width", count=count)

    @classmethod
    def edges(
        cls,
        edges: Sequence[float],
        *,
        out_of_range: OutOfRangePolicy = "raise",
    ) -> BucketSpec:
        """Create fixed numeric-edge buckets."""

        return cls("edges", boundaries=tuple(edges), out_of_range=out_of_range)

    @classmethod
    def threshold(
        cls,
        value: float,
        *,
        equal_to: EqualToPolicy = "upper",
    ) -> BucketSpec:
        """Create two buckets separated by one explicit threshold."""

        return cls("threshold", split_at=value, equal_to=equal_to)

    def to_parameters(self) -> Mapping[str, JsonValue]:
        """Return the canonical result-affecting bucket policy."""

        return MappingProxyType(
            {
                "kind": self.kind,
                "count": self.count,
                "boundaries": self.boundaries,
                "tie_policy": self.tie_policy,
                "split_at": self.split_at,
                "equal_to": self.equal_to,
                "out_of_range": self.out_of_range,
            }
        )


@dataclass(frozen=True, slots=True)
class SignalTransformResult:
    """Owned canonical signal frame plus compact transformation evidence."""

    _frame: pl.DataFrame
    evidence: AnalysisResult

    @property
    def frame(self) -> pl.DataFrame:
        """Return a shallow clone of the result-owned frame."""

        return self._frame.clone()

    @property
    def metadata(self) -> ResultMetadata:
        """Expose transformation provenance."""

        return self.evidence.metadata

    def to_json(self, *, indent: int | None = 2) -> str:
        """Serialize compact evidence while keeping the signal frame columnar."""

        return self.evidence.to_json(indent=indent)


def _normalized_by(by: str | Sequence[str], *, time: str) -> tuple[str, ...]:
    raw = (by,) if isinstance(by, str) else tuple(by)
    if not raw or any(not isinstance(key, str) or not key for key in raw):
        raise MethodContractError("by must contain at least one non-empty column name")
    if len(set(raw)) != len(raw):
        raise MethodContractError("by columns must be unique")
    return tuple("observation_time" if key == time else key for key in raw)


def _availability_finding(
    *, grouped: bool, availability_column: str | None, verified: bool
) -> tuple[Finding, ...]:
    if not grouped:
        return ()
    if verified:
        return (
            Finding(
                code="GROUP_AVAILABILITY_VERIFIED",
                title="Group attributes satisfy the availability cutoff",
                message="Every grouped row was available by its observation time.",
                state=FindingState.PASS,
                severity=Severity.INFO,
                category="temporal_integrity",
                evidence={"available_time_column": availability_column},
            ),
        )
    return (
        Finding(
            code="GROUP_AVAILABILITY_UNKNOWN",
            title="Group availability is not established",
            message=(
                "Grouped analysis cannot prove that classifications were historically available."
            ),
            state=FindingState.UNKNOWN,
            severity=Severity.HIGH,
            category="temporal_integrity",
        ),
    )


def _canonical_signal(
    signal: object,
    *,
    time: str,
    instrument: str,
    signal_value: str,
    extra_columns: Sequence[str],
    available_time: str | None,
    null_policy: Literal["drop", "raise"],
) -> tuple[pl.DataFrame, FrameDiagnostics | None, int, int, bool]:
    if isinstance(signal, np.ndarray):
        if signal.ndim != 1:
            raise DataContractError("NumPy signal input must be one-dimensional")
        if extra_columns or available_time is not None:
            raise DataContractError(
                "NumPy signal input cannot provide grouping or availability columns"
            )
        frame = pl.DataFrame(
            {
                "observation_time": np.zeros(signal.size, dtype=np.int64),
                "instrument": np.arange(signal.size, dtype=np.int64),
                "signal": signal,
            }
        )
        normalized, excluded = paired_numeric_policy(frame, ["signal"], null_policy=null_policy)
        return normalized, None, int(signal.size), excluded, False

    required = [time, instrument, signal_value, *extra_columns]
    if available_time is not None:
        required.append(available_time)
    frame, diagnostics = eager_frame(signal, required=tuple(dict.fromkeys(required)))
    validate_panel_schema(
        frame,
        time=time,
        instrument=instrument,
        numeric=[signal_value],
        name="signal",
    )
    require_no_nulls(frame, extra_columns, name="signal grouping columns")
    expressions = [
        pl.col(time).alias("observation_time"),
        pl.col(instrument).alias("instrument"),
        pl.col(signal_value).cast(pl.Float64).alias("signal"),
    ]
    for column in extra_columns:
        if column not in {time, instrument, signal_value, available_time}:
            expressions.append(pl.col(column))
    verified = False
    if available_time is not None:
        require_no_nulls(frame, [available_time], name="signal availability")
        require_compatible_keys(frame, frame, pairs=((time, available_time),))
        future = int(frame.select((pl.col(available_time) > pl.col(time)).sum()).item())
        if future:
            raise DataContractError(
                f"signal contains {future} grouped rows available after observation time"
            )
        expressions.append(pl.col(available_time).alias("available_time"))
        verified = True
    projected = frame.select(expressions)
    projected, excluded = paired_numeric_policy(projected, ["signal"], null_policy=null_policy)
    return projected, diagnostics, frame.height, excluded, verified


def _average_rank(values: FloatArray) -> FloatArray:
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(values.size, dtype=np.float64)
    start = 0
    while start < values.size:
        end = start + 1
        while end < values.size and values[order[end]] == values[order[start]]:
            end += 1
        ranks[order[start:end]] = (start + 1 + end) / 2.0
        start = end
    return ranks


def _quantile_assignments(values: FloatArray, spec: BucketSpec) -> npt.NDArray[np.int32]:
    assert spec.count is not None
    if spec.tie_policy == "balanced":
        positions = (np.arange(values.size, dtype=np.float64) + 0.5) / values.size
    else:
        positions = (_average_rank(values) - 0.5) / values.size
    boundaries = (
        np.asarray(spec.boundaries, dtype=np.float64)
        if spec.boundaries
        else np.linspace(0.0, 1.0, spec.count + 1)
    )
    return (np.searchsorted(boundaries[1:-1], positions, side="right") + 1).astype(np.int32)


def _assign_bucket_group(
    group: pl.DataFrame,
    spec: BucketSpec,
    *,
    ascending: bool,
) -> tuple[pl.DataFrame, int]:
    assert spec.count is not None
    ordered = group.sort(["signal", "instrument"], descending=[not ascending, False])
    values: FloatArray = ordered.get_column("signal").to_numpy().astype(np.float64, copy=False)
    if spec.kind == "quantile":
        if spec.split_at is None:
            if ordered.height < spec.count:
                raise DataContractError(
                    f"bucket group has {ordered.height} rows but requires at least {spec.count}"
                )
            assignments = _quantile_assignments(values, spec)
        else:
            threshold = spec.split_at
            assert threshold is not None
            lower_mask = values <= threshold if spec.equal_to == "lower" else values < threshold
            lower_count = spec.count // 2
            upper_count = spec.count - lower_count
            if int(lower_mask.sum()) < lower_count or int((~lower_mask).sum()) < upper_count:
                raise DataContractError(
                    "split-aware quantile group lacks rows on one side of the split"
                )
            assignments = np.empty(values.size, dtype=np.int32)
            lower_spec = BucketSpec.quantiles(lower_count, tie_policy=spec.tie_policy)
            upper_spec = BucketSpec.quantiles(upper_count, tie_policy=spec.tie_policy)
            assignments[lower_mask] = _quantile_assignments(values[lower_mask], lower_spec)
            assignments[~lower_mask] = (
                _quantile_assignments(values[~lower_mask], upper_spec) + lower_count
            )
    elif spec.kind == "equal_width":
        minimum = float(values.min())
        maximum = float(values.max())
        if minimum == maximum:
            raise DataContractError("equal-width buckets are undefined for a constant group")
        edges = np.linspace(minimum, maximum, spec.count + 1)
        assignments = (np.searchsorted(edges[1:-1], values, side="right") + 1).astype(np.int32)
    elif spec.kind == "edges":
        edges = np.asarray(spec.boundaries, dtype=np.float64)
        in_range = (values >= edges[0]) & (values <= edges[-1])
        out_of_range = int((~in_range).sum())
        if out_of_range and spec.out_of_range == "raise":
            raise DataContractError(
                f"numeric bucket edges exclude {out_of_range} finite signal rows"
            )
        if out_of_range:
            ordered = ordered.filter(pl.Series(in_range))
            values = values[in_range]
        assignments = (np.searchsorted(edges[1:-1], values, side="right") + 1).astype(np.int32)
        return ordered.with_columns(pl.Series("bucket", assignments)), out_of_range
    else:
        threshold_value = spec.split_at
        assert threshold_value is not None
        lower = values <= threshold_value if spec.equal_to == "lower" else values < threshold_value
        assignments = np.where(lower, 1, 2).astype(np.int32)
    return ordered.with_columns(pl.Series("bucket", assignments)), 0


def bucketize(
    signal: object,
    *,
    spec: BucketSpec | None = None,
    by: str | Sequence[str] = "time",
    time: str = "time",
    instrument: str = "instrument",
    signal_value: str = "signal",
    available_time: str | None = None,
    ascending: bool = True,
    small_group_policy: SmallGroupPolicy = "raise",
    null_policy: Literal["drop", "raise"] = "drop",
) -> SignalTransformResult:
    """Assign every eligible signal row to one explicit deterministic bucket."""

    selected = BucketSpec.quantiles() if spec is None else spec
    if not isinstance(selected, BucketSpec):
        raise MethodContractError("spec must be a BucketSpec")
    if small_group_policy not in {"raise", "drop"}:
        raise MethodContractError("small_group_policy must be 'raise' or 'drop'")
    normalized_by = _normalized_by(by, time=time)
    source_by = tuple(time if key == "observation_time" else key for key in normalized_by)
    extra_columns = tuple(key for key in source_by if key not in {time, instrument, signal_value})
    frame, diagnostics, input_rows, numeric_excluded, availability_verified = _canonical_signal(
        signal,
        time=time,
        instrument=instrument,
        signal_value=signal_value,
        extra_columns=extra_columns,
        available_time=available_time,
        null_policy=null_policy,
    )
    retained_after_numeric = frame.height
    if frame.is_empty():
        raise DataContractError("signal has no finite observations")

    assigned: list[pl.DataFrame] = []
    dropped_groups = 0
    dropped_group_count = 0
    out_of_range = 0
    for group in frame.sort([*normalized_by, "instrument"]).partition_by(
        list(normalized_by), maintain_order=True
    ):
        try:
            result, excluded = _assign_bucket_group(group, selected, ascending=ascending)
        except DataContractError:
            if small_group_policy == "raise":
                raise
            dropped_groups += group.height
            dropped_group_count += 1
            continue
        out_of_range += excluded
        assigned.append(result)
    if not assigned:
        if selected.kind == "quantile":
            raise DataContractError(
                f"no groups contain at least {selected.count} observations for bucket assignment"
            )
        raise DataContractError("no signal groups remain after bucket assignment")
    output = pl.concat(assigned, how="vertical").sort([*normalized_by, "bucket", "instrument"])
    counts = (
        output.group_by([*normalized_by, "bucket"], maintain_order=True)
        .len(name="n_observations")
        .sort([*normalized_by, "bucket"])
    )
    effective = output.get_column("bucket").n_unique()
    assert selected.count is not None
    findings = list(
        _availability_finding(
            grouped=any(key != "observation_time" for key in normalized_by),
            availability_column=available_time,
            verified=availability_verified,
        )
    )
    if effective < selected.count:
        findings.append(
            Finding(
                code="BUCKETS_EFFECTIVE_COUNT_REDUCED",
                title="Fewer buckets were populated than requested",
                message="Tie preservation or sample support left one or more buckets empty.",
                state=FindingState.WARN,
                severity=Severity.MEDIUM,
                category="statistical_validity",
                evidence={"requested_buckets": selected.count, "effective_buckets": effective},
            )
        )
    if dropped_group_count:
        findings.append(
            Finding(
                code="BUCKET_UNDERSIZED_GROUPS",
                title="Some bucket groups were excluded",
                message="Groups without enough support for the requested buckets were excluded.",
                state=FindingState.WARN,
                severity=Severity.MEDIUM,
                category="statistical_validity",
                evidence={
                    "excluded_groups": dropped_group_count,
                    "excluded_rows": dropped_groups,
                },
            )
        )
    attrition: tuple[JsonValue, ...] = (
        attrition_record(
            "numeric_policy",
            "null_or_nan_signal",
            input_rows=input_rows,
            retained_rows=retained_after_numeric,
            policy=null_policy,
        ),
        attrition_record(
            "bucket_assignment",
            "undersized_group_or_out_of_range",
            input_rows=retained_after_numeric,
            retained_rows=output.height,
            policy=(f"small_group={small_group_policy};out_of_range={selected.out_of_range}"),
        ),
    )
    evidence = AnalysisResult(
        metadata=ResultMetadata(
            method="signal.bucketize",
            method_version=1,
            parameters={
                "spec": selected.to_parameters(),
                "by": normalized_by,
                "ascending": ascending,
                "available_time": available_time,
                "small_group_policy": small_group_policy,
                "null_policy": null_policy,
                "input": diagnostics.to_parameters()
                if diagnostics is not None
                else {
                    "source_type": "numpy.ndarray",
                    "rows": input_rows,
                },
            },
        ),
        metrics={
            "input_rows": input_rows,
            "retained_rows": output.height,
            "excluded_rows": input_rows - output.height,
            "excluded_numeric_rows": numeric_excluded,
            "excluded_bucket_rows": dropped_groups + out_of_range,
            "excluded_groups": dropped_group_count,
            "requested_buckets": selected.count,
            "effective_buckets": effective,
        },
        findings=tuple(findings),
        tables={
            "bucket_counts": frame_records(counts),
            "data_attrition": attrition,
        },
    )
    return SignalTransformResult(_frame=output, evidence=evidence)


def _stable_levels(values: Sequence[object]) -> tuple[object, ...]:
    return tuple(sorted(set(values), key=lambda value: (type(value).__name__, str(value))))


def neutralize(
    signal: object,
    *,
    exposures: Sequence[str],
    exposure_data: object | None = None,
    categorical: Sequence[str] = (),
    by: str | Sequence[str] = "time",
    signal_time: str = "time",
    exposure_time: str = "time",
    instrument: str = "instrument",
    signal_value: str = "signal",
    weight: str | None = None,
    available_time: str | None = None,
    intercept: bool = True,
    min_residual_df: int = 2,
    insufficient_policy: SmallGroupPolicy = "raise",
    null_policy: Literal["drop", "raise"] = "drop",
) -> SignalTransformResult:
    """Residualize a signal against declared, already aligned exposures."""

    exposure_names = tuple(exposures)
    categorical_names = tuple(categorical)
    if not exposure_names or any(not name for name in exposure_names):
        raise MethodContractError("exposures must contain non-empty column names")
    if len(set(exposure_names)) != len(exposure_names):
        raise MethodContractError("exposures must be unique")
    if not set(categorical_names).issubset(exposure_names):
        raise MethodContractError("categorical columns must be a subset of exposures")
    if min_residual_df < 1:
        raise MethodContractError("min_residual_df must be positive")
    if insufficient_policy not in {"raise", "drop"}:
        raise MethodContractError("insufficient_policy must be 'raise' or 'drop'")
    normalized_by = _normalized_by(by, time=signal_time)
    source_by = tuple(signal_time if key == "observation_time" else key for key in normalized_by)

    signal_required = [signal_time, instrument, signal_value]
    if exposure_data is None:
        signal_required.extend(exposure_names)
        signal_required.extend(key for key in source_by if key not in signal_required)
        if weight is not None:
            signal_required.append(weight)
        if available_time is not None:
            signal_required.append(available_time)
    signal_frame, signal_diagnostics = eager_frame(
        signal, required=tuple(dict.fromkeys(signal_required))
    )
    validate_panel_schema(
        signal_frame,
        time=signal_time,
        instrument=instrument,
        numeric=[signal_value],
        name="signal",
    )
    signal_projection = signal_frame.select(
        pl.col(signal_time).alias("observation_time"),
        pl.col(instrument).alias("instrument"),
        pl.col(signal_value).cast(pl.Float64).alias("source_signal"),
        *[
            pl.col(column)
            for column in source_by
            if column not in {signal_time, instrument, signal_value}
        ],
    )

    if exposure_data is None:
        exposure_frame = signal_frame
        exposure_diagnostics = signal_diagnostics
        exposure_time = signal_time
    else:
        required = [exposure_time, instrument, *exposure_names]
        if weight is not None:
            required.append(weight)
        if available_time is not None:
            required.append(available_time)
        exposure_frame, exposure_diagnostics = eager_frame(
            exposure_data, required=tuple(dict.fromkeys(required))
        )
        validate_panel_schema(
            exposure_frame,
            time=exposure_time,
            instrument=instrument,
            numeric=(),
            name="exposures",
        )
        require_compatible_keys(
            signal_frame,
            exposure_frame,
            pairs=((signal_time, exposure_time), (instrument, instrument)),
        )

    continuous = tuple(name for name in exposure_names if name not in categorical_names)
    require_numeric(exposure_frame, continuous)
    if weight is not None:
        require_numeric(exposure_frame, [weight])
    require_no_nulls(exposure_frame, categorical_names, name="categorical exposures")
    require_unique(exposure_frame, [exposure_time, instrument], name="exposures")
    availability_verified = False
    if available_time is not None:
        require_no_nulls(exposure_frame, [available_time], name="exposure availability")
        require_compatible_keys(
            exposure_frame, exposure_frame, pairs=((exposure_time, available_time),)
        )
        future = int(
            exposure_frame.select((pl.col(available_time) > pl.col(exposure_time)).sum()).item()
        )
        if future:
            raise DataContractError(
                f"exposures contain {future} rows available after observation time"
            )
        availability_verified = True

    exposure_projection = exposure_frame.select(
        pl.col(exposure_time).alias("observation_time"),
        pl.col(instrument).alias("instrument"),
        *[pl.col(name) for name in exposure_names],
        *([pl.col(weight).cast(pl.Float64).alias("_weight")] if weight is not None else []),
        *([pl.col(available_time).alias("available_time")] if available_time is not None else []),
    )
    if exposure_data is None:
        panel = signal_projection.join(
            exposure_projection,
            on=["observation_time", "instrument"],
            how="inner",
            validate="1:1",
        )
    else:
        panel = signal_projection.join(
            exposure_projection,
            on=["observation_time", "instrument"],
            how="inner",
            validate="1:1",
        )
    matched_rows = panel.height
    numeric_policy_columns = ["source_signal", *continuous]
    if weight is not None:
        numeric_policy_columns.append("_weight")
    panel, numeric_excluded = paired_numeric_policy(
        panel, numeric_policy_columns, null_policy=null_policy
    )
    if weight is not None:
        invalid_weight = int(panel.select((pl.col("_weight") <= 0.0).sum()).item())
        if invalid_weight:
            raise DataContractError(
                f"neutralization weights must be positive; found {invalid_weight} invalid rows"
            )
    if panel.is_empty():
        raise DataContractError("no finite aligned signal/exposure rows remain")

    outputs: list[pl.DataFrame] = []
    diagnostics_rows: list[dict[str, object]] = []
    coefficient_rows: list[dict[str, object]] = []
    excluded_groups = 0
    rank_deficient_groups = 0
    group_keys = list(normalized_by)
    for group in panel.sort([*group_keys, "instrument"]).partition_by(
        group_keys, maintain_order=True
    ):
        group_identity = {key: group.get_column(key)[0] for key in group_keys}
        columns: list[FloatArray] = []
        coefficient_identity: list[tuple[str, str, object | None]] = []
        if intercept:
            columns.append(np.ones(group.height, dtype=np.float64))
            coefficient_identity.append(("intercept", "intercept", None))
        for name in continuous:
            columns.append(group.get_column(name).to_numpy().astype(np.float64, copy=False))
            coefficient_identity.append((name, "continuous", None))
        for name in categorical_names:
            raw_values = group.get_column(name).to_list()
            levels = _stable_levels(raw_values)
            for level in levels[1:]:
                columns.append(
                    np.asarray([value == level for value in raw_values], dtype=np.float64)
                )
                coefficient_identity.append((name, "categorical", level))
        if not columns:
            raise MethodContractError("neutralization requires an intercept or exposure columns")
        design = np.column_stack(columns)
        response: FloatArray = (
            group.get_column("source_signal").to_numpy().astype(np.float64, copy=False)
        )
        weights: FloatArray = (
            group.get_column("_weight").to_numpy().astype(np.float64, copy=False)
            if weight is not None
            else np.ones(group.height, dtype=np.float64)
        )
        root_weight = np.sqrt(weights)
        weighted_design = design * root_weight[:, None]
        weighted_response = response * root_weight
        coefficients, _, rank, singular_values = np.linalg.lstsq(
            weighted_design, weighted_response, rcond=None
        )
        residual_df = group.height - int(rank)
        if residual_df < min_residual_df:
            if insufficient_policy == "raise":
                raise DataContractError(
                    "neutralization group has insufficient residual degrees of freedom"
                )
            excluded_groups += group.height
            continue
        if int(rank) < design.shape[1]:
            rank_deficient_groups += 1
        residual = response - design @ coefficients
        output = group.with_columns(pl.Series("signal", residual, dtype=pl.Float64)).select(
            "observation_time",
            "instrument",
            "source_signal",
            "signal",
            *[key for key in group_keys if key != "observation_time"],
            *(["available_time"] if "available_time" in group.columns else []),
        )
        outputs.append(output)
        weighted_mean = float(np.average(response, weights=weights))
        total = float(np.sum(weights * np.square(response - weighted_mean)))
        residual_sum = float(np.sum(weights * np.square(residual)))
        condition = (
            float(singular_values[0] / singular_values[-1])
            if singular_values.size and singular_values[-1] > 0.0
            else None
        )
        diagnostics_rows.append(
            {
                **group_identity,
                "n_observations": group.height,
                "n_parameters": design.shape[1],
                "rank": int(rank),
                "residual_df": residual_df,
                "condition_number": condition,
                "weighted_r_squared": 1.0 - residual_sum / total if total > 0.0 else None,
            }
        )
        for (name, kind, level), coefficient in zip(
            coefficient_identity, coefficients, strict=True
        ):
            coefficient_rows.append(
                {
                    **group_identity,
                    "exposure": name,
                    "kind": kind,
                    "level": level,
                    "coefficient": float(coefficient),
                }
            )
    if not outputs:
        raise DataContractError("no groups remain after neutralization")
    output_frame = pl.concat(outputs, how="vertical").sort([*group_keys, "instrument"])
    findings = list(
        _availability_finding(
            grouped=True,
            availability_column=available_time,
            verified=availability_verified,
        )
    )
    if rank_deficient_groups:
        findings.append(
            Finding(
                code="NEUTRALIZATION_RANK_DEFICIENT",
                title="Some neutralization designs are rank deficient",
                message="Minimum-norm weighted least-squares residuals were returned.",
                state=FindingState.WARN,
                severity=Severity.MEDIUM,
                category="statistical_validity",
                evidence={"rank_deficient_groups": rank_deficient_groups},
            )
        )
    attrition: tuple[JsonValue, ...] = (
        attrition_record(
            "alignment",
            "missing_signal_or_exposure_key",
            input_rows=signal_frame.height,
            retained_rows=matched_rows,
            policy="inner_join",
        ),
        attrition_record(
            "numeric_policy",
            "null_or_nan_analytical_value",
            input_rows=matched_rows,
            retained_rows=matched_rows - numeric_excluded,
            policy=null_policy,
        ),
        attrition_record(
            "regression_eligibility",
            "insufficient_residual_degrees_of_freedom",
            input_rows=matched_rows - numeric_excluded,
            retained_rows=output_frame.height,
            policy=insufficient_policy,
        ),
    )
    evidence = AnalysisResult(
        metadata=ResultMetadata(
            method="signal.neutralize",
            method_version=1,
            parameters={
                "exposures": exposure_names,
                "categorical": categorical_names,
                "by": normalized_by,
                "weight": weight,
                "available_time": available_time,
                "intercept": intercept,
                "minimum_residual_df": min_residual_df,
                "insufficient_policy": insufficient_policy,
                "null_policy": null_policy,
                "backend": "numpy.linalg.lstsq",
                "signal_input": signal_diagnostics.to_parameters(),
                "exposure_input": exposure_diagnostics.to_parameters(),
            },
        ),
        metrics={
            "input_signal_rows": signal_frame.height,
            "matched_rows": matched_rows,
            "retained_rows": output_frame.height,
            "excluded_rows": signal_frame.height - output_frame.height,
            "rank_deficient_groups": rank_deficient_groups,
            "n_groups": len(diagnostics_rows),
        },
        findings=tuple(findings),
        tables={
            "neutralization_diagnostics": frame_records(pl.DataFrame(diagnostics_rows)),
            "neutralization_coefficients": frame_records(pl.DataFrame(coefficient_rows)),
            "data_attrition": attrition,
        },
    )
    return SignalTransformResult(_frame=output_frame, evidence=evidence)


__all__ = ["BucketSpec", "SignalTransformResult", "bucketize", "neutralize"]
