"""Cross-sectional signal diagnostics."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from numbers import Real
from typing import Any, Literal, TypeAlias, cast

import numpy as np
import numpy.typing as npt
import polars as pl

from lacuna._attrition import attrition_record
from lacuna._decay import fit_decay
from lacuna._frames import (
    FrameDiagnostics,
    eager_frame,
    frame_records,
    paired_numeric_policy,
    require_compatible_keys,
    require_no_nulls,
    require_unique,
    validate_label_intervals,
    validate_panel_schema,
)
from lacuna._native_arrays import readonly_float64, readonly_int64
from lacuna._portfolio import PortfolioProjectionResult, portfolio_projection
from lacuna._signal_transform import (
    BucketSpec,
    SignalTransformResult,
    bucketize,
    neutralize,
)
from lacuna.exceptions import DataContractError, MethodContractError
from lacuna.labels import Horizon, LabelResult, forward_returns
from lacuna.types import AnalysisResult, Finding, FindingState, JsonValue, ResultMetadata, Severity

CorrelationMethod: TypeAlias = Literal["pearson", "spearman"]
FloatArray: TypeAlias = npt.NDArray[np.float64]


def _float_or_none(value: object) -> float | None:
    if value is None:
        return None
    if not isinstance(value, Real):
        raise TypeError(f"expected a numeric scalar, received {type(value).__name__}")
    result = float(value)
    return result if math.isfinite(result) else None


def _average_rank(
    values: FloatArray,
) -> FloatArray:
    order = np.argsort(values, kind="mergesort")
    ranks: FloatArray = np.empty(values.size, dtype=np.float64)
    start = 0
    while start < values.size:
        end = start + 1
        while end < values.size and values[order[end]] == values[order[start]]:
            end += 1
        ranks[order[start:end]] = (start + 1 + end) / 2.0
        start = end
    return ranks


def _pearson(
    left: FloatArray,
    right: FloatArray,
) -> float | None:
    if left.size < 2 or right.size != left.size:
        return None
    left_centered = left - left.mean()
    right_centered = right - right.mean()
    denominator = math.sqrt(
        float(np.dot(left_centered, left_centered) * np.dot(right_centered, right_centered))
    )
    if denominator == 0.0:
        return None
    return float(np.clip(np.dot(left_centered, right_centered) / denominator, -1.0, 1.0))


def _correlation(
    left: FloatArray,
    right: FloatArray,
    method: CorrelationMethod,
) -> float | None:
    if method == "spearman":
        return _pearson(_average_rank(left), _average_rank(right))
    return _pearson(left, right)


def _array_panel(
    signal_values: np.ndarray[Any, Any],
    label_values: np.ndarray[Any, Any],
) -> tuple[pl.DataFrame, FrameDiagnostics, FrameDiagnostics]:
    if signal_values.ndim != 1 or label_values.ndim != 1:
        raise DataContractError("NumPy signal and label inputs must both be one-dimensional")
    if signal_values.shape[0] != label_values.shape[0]:
        raise DataContractError("NumPy signal and label inputs must have equal lengths")
    frame = pl.DataFrame(
        {
            "observation_time": np.zeros(signal_values.shape[0], dtype=np.int64),
            "instrument": np.arange(signal_values.shape[0], dtype=np.int64),
            "signal": signal_values,
            "forward_return": label_values,
        }
    )
    signal_diagnostics = FrameDiagnostics(
        source_type="numpy.ndarray",
        rows=signal_values.shape[0],
        columns=("signal",),
        lazy_input=False,
        materialized=False,
        adapter_copy="potentially_zero_copy",
        adapter_operations=("numpy_to_polars",),
        execution_operations=("construct_aligned_array_panel",),
    )
    label_diagnostics = FrameDiagnostics(
        source_type="numpy.ndarray",
        rows=label_values.shape[0],
        columns=("forward_return",),
        lazy_input=False,
        materialized=False,
        adapter_copy="potentially_zero_copy",
        adapter_operations=("numpy_to_polars",),
        execution_operations=("construct_aligned_array_panel",),
    )
    return frame, signal_diagnostics, label_diagnostics


def _aligned_panel(
    signal_data: object,
    labels: object,
    *,
    signal_time: str,
    label_time: str,
    instrument: str,
    signal_value: str,
    label_value: str,
    null_policy: Literal["drop", "raise"],
    extra_signal_columns: Sequence[str] = (),
) -> tuple[pl.DataFrame, FrameDiagnostics, FrameDiagnostics, int, int, int]:
    if isinstance(signal_data, np.ndarray) and isinstance(labels, np.ndarray):
        if extra_signal_columns:
            raise DataContractError("NumPy signal input cannot provide grouping columns")
        panel, signal_diagnostics, label_diagnostics = _array_panel(signal_data, labels)
        panel, excluded = paired_numeric_policy(
            panel, ["signal", "forward_return"], null_policy=null_policy
        )
        return (
            panel,
            signal_diagnostics,
            label_diagnostics,
            excluded,
            signal_values_count(signal_data),
            panel.height,
        )

    signal_frame, signal_diagnostics = eager_frame(
        signal_data,
        required=[signal_time, instrument, signal_value, *extra_signal_columns],
    )
    label_source = labels.frame if isinstance(labels, LabelResult) else labels
    label_frame, label_diagnostics = eager_frame(
        label_source,
        required=[label_time, instrument, label_value],
    )
    validate_panel_schema(
        signal_frame,
        time=signal_time,
        instrument=instrument,
        numeric=[signal_value],
        name="signal",
    )
    require_no_nulls(signal_frame, extra_signal_columns, name="signal grouping columns")
    label_key = [label_time, instrument]
    if "horizon" in label_frame.columns:
        label_key.append("horizon")
    validate_panel_schema(
        label_frame,
        time=label_time,
        instrument=instrument,
        numeric=[label_value],
        name="labels",
        unique=False,
    )
    require_unique(label_frame, label_key, name="labels")
    validate_label_intervals(label_frame, observation_time=label_time)
    require_compatible_keys(
        signal_frame,
        label_frame,
        pairs=((signal_time, label_time), (instrument, instrument)),
    )
    signal_diagnostics = signal_diagnostics.with_execution(
        "validate_signal_frame",
        "project_and_cast_float64",
        "inner_join_signal_labels",
    )
    label_diagnostics = label_diagnostics.with_execution(
        "validate_label_frame",
        "project_and_cast_float64",
        "inner_join_signal_labels",
    )

    signal_expressions = [
        pl.col(signal_time).alias("observation_time"),
        pl.col(instrument).alias("instrument"),
        pl.col(signal_value).cast(pl.Float64).alias("signal"),
    ]
    for column in extra_signal_columns:
        if column not in {signal_time, instrument, signal_value}:
            signal_expressions.append(pl.col(column))
    signal_projection = signal_frame.select(signal_expressions)
    label_expressions = [
        pl.col(label_time).alias("observation_time"),
        pl.col(instrument).alias("instrument"),
        pl.col(label_value).cast(pl.Float64).alias("forward_return"),
    ]
    for optional in ("horizon", "label_start", "entry_time", "label_end"):
        if optional in label_frame.columns:
            label_expressions.append(pl.col(optional))
    label_projection = label_frame.select(label_expressions)
    aligned = signal_projection.join(
        label_projection,
        on=["observation_time", "instrument"],
        how="inner",
        validate="1:m" if "horizon" in label_projection.columns else "1:1",
    )
    matched_before_policy = aligned.height
    aligned, excluded = paired_numeric_policy(
        aligned,
        ["signal", "forward_return"],
        null_policy=null_policy,
    )
    if aligned.is_empty():
        raise DataContractError("no aligned finite signal/label observations remain")
    return (
        aligned,
        signal_diagnostics,
        label_diagnostics,
        excluded,
        signal_frame.height,
        matched_before_policy,
    )


def signal_values_count(values: np.ndarray[Any, Any]) -> int:
    """Return the row count without lossy integer casts in callers."""

    return int(values.shape[0])


def _group_keys(panel: pl.DataFrame, by: str | Sequence[str] | None) -> list[str]:
    if by is None:
        keys: list[str] = []
    elif isinstance(by, str):
        keys = [by]
    else:
        keys = list(by)
    missing = [key for key in keys if key not in panel.columns]
    if missing:
        raise DataContractError(f"unknown grouping columns: {', '.join(missing)}")
    if "horizon" in panel.columns and "horizon" not in keys:
        keys.append("horizon")
    return keys


def _normalized_group_request(
    by: str | Sequence[str] | None,
    *,
    signal_time: str,
) -> tuple[str, ...]:
    if by is None:
        return ()
    raw = (by,) if isinstance(by, str) else tuple(by)
    if any(not key for key in raw) or len(set(raw)) != len(raw):
        raise MethodContractError("by must contain unique non-empty column names")
    return tuple("observation_time" if key == signal_time else key for key in raw)


def _group_availability_findings(
    panel: pl.DataFrame,
    *,
    keys: Sequence[str],
    available_time: str | None,
) -> tuple[Finding, ...]:
    group_dimensions = [key for key in keys if key not in {"observation_time", "horizon"}]
    if not group_dimensions:
        return ()
    if available_time is None:
        return (
            Finding(
                code="GROUP_AVAILABILITY_UNKNOWN",
                title="Group availability is not established",
                message=(
                    "Grouped analysis cannot prove that classifications were historically "
                    "available."
                ),
                state=FindingState.UNKNOWN,
                severity=Severity.HIGH,
                category="temporal_integrity",
                evidence={"group_columns": tuple(group_dimensions)},
            ),
        )
    if panel.schema[available_time] != panel.schema["observation_time"]:
        raise DataContractError(
            "group availability and observation-time columns must use matching dtypes"
        )
    future = int(panel.select((pl.col(available_time) > pl.col("observation_time")).sum()).item())
    if future:
        raise DataContractError(
            f"group attributes contain {future} rows available after observation time"
        )
    return (
        Finding(
            code="GROUP_AVAILABILITY_VERIFIED",
            title="Group attributes satisfy the availability cutoff",
            message="Every grouped row was available by its observation time.",
            state=FindingState.PASS,
            severity=Severity.INFO,
            category="temporal_integrity",
            evidence={
                "group_columns": tuple(group_dimensions),
                "available_time_column": available_time,
            },
        ),
    )


def _reference_grouped_ic(
    panel: pl.DataFrame,
    group_keys: Sequence[str],
    method: CorrelationMethod,
) -> pl.DataFrame:
    working = panel.with_columns(pl.lit(0).alias("_single_group")) if not group_keys else panel
    keys = ["_single_group"] if not group_keys else list(group_keys)
    records: list[dict[str, object]] = []
    for group in working.partition_by(keys, maintain_order=True):
        record = {key: group.get_column(key)[0] for key in keys}
        left: FloatArray = group.get_column("signal").to_numpy().astype(np.float64, copy=False)
        right: FloatArray = (
            group.get_column("forward_return").to_numpy().astype(np.float64, copy=False)
        )
        record.update({"ic": _correlation(left, right, method), "n_observations": group.height})
        records.append(record)
    result = pl.DataFrame(records)
    return result.drop("_single_group") if not group_keys else result


def _native_grouped_rank_ic(panel: pl.DataFrame, group_keys: Sequence[str]) -> pl.DataFrame:
    from lacuna import _native

    working = panel.with_columns(pl.lit(0).alias("_single_group")) if not group_keys else panel
    keys = ["_single_group"] if not group_keys else list(group_keys)
    ordered = working.sort(keys)
    groups = ordered.group_by(keys, maintain_order=True).len(name="n_observations")
    counts: npt.NDArray[np.int64] = (
        groups.get_column("n_observations").to_numpy().astype(np.int64, copy=False)
    )
    offsets: npt.NDArray[np.int64] = np.empty(counts.size + 1, dtype=np.int64)
    offsets[0] = 0
    np.cumsum(counts, dtype=np.int64, out=offsets[1:])
    signal = readonly_float64(ordered.get_column("signal"), name="signal").values
    labels = readonly_float64(ordered.get_column("forward_return"), name="labels").values
    native_offsets = readonly_int64(offsets, name="offsets").values
    correlations, validity = _native.grouped_rank_ic(
        signal,
        labels,
        native_offsets,
    )
    if not np.isin(validity, (0, 1)).all():
        raise RuntimeError("native grouped rank IC returned an invalid validity code")
    ic_values = pl.Series("ic", correlations, dtype=pl.Float64)
    if not validity.all():
        ic_values = ic_values.set(pl.Series(validity == 0), None)
    result = groups.with_columns(ic_values)
    return result.drop("_single_group") if not group_keys else result


def _ic_metrics(values: Sequence[float], n_observations: int) -> dict[str, JsonValue]:
    array: FloatArray = np.asarray(values, dtype=np.float64)
    count = int(array.size)
    if count == 0:
        return {
            "mean_ic": None,
            "median_ic": None,
            "std_ic": None,
            "ic_information_ratio": None,
            "t_statistic": None,
            "positive_fraction": None,
            "n_periods": 0,
            "n_observations": n_observations,
        }
    mean = float(array.mean())
    median = float(np.median(array))
    standard_deviation = float(array.std(ddof=1)) if count > 1 else None
    information_ratio = (
        mean / standard_deviation
        if standard_deviation is not None and standard_deviation > 0.0
        else None
    )
    t_statistic = (
        mean / (standard_deviation / math.sqrt(count))
        if standard_deviation is not None and standard_deviation > 0.0
        else None
    )
    return {
        "mean_ic": mean,
        "median_ic": median,
        "std_ic": standard_deviation,
        "ic_information_ratio": information_ratio,
        "t_statistic": t_statistic,
        "positive_fraction": float(np.mean(array > 0.0)),
        "n_periods": count,
        "n_observations": n_observations,
    }


def _horizon_summary(period_ic: pl.DataFrame) -> pl.DataFrame:
    if "horizon" not in period_ic.columns:
        return pl.DataFrame()
    summary_keys = [
        column
        for column in period_ic.columns
        if column not in {"observation_time", "ic", "n_observations"}
    ]
    return (
        period_ic.group_by(summary_keys, maintain_order=True)
        .agg(
            pl.col("ic").drop_nulls().mean().alias("mean_ic"),
            pl.col("ic").drop_nulls().median().alias("median_ic"),
            pl.col("ic").drop_nulls().std(ddof=1).alias("std_ic"),
            pl.col("ic").drop_nulls().len().alias("n_periods"),
            pl.col("n_observations").sum(),
        )
        .with_columns((pl.col("mean_ic") / pl.col("std_ic")).alias("ic_information_ratio"))
        .sort(summary_keys)
    )


def ic(
    signal: object,
    labels: object,
    *,
    method: CorrelationMethod = "spearman",
    by: str | Sequence[str] | None = "observation_time",
    signal_time: str = "time",
    label_time: str = "observation_time",
    instrument: str = "instrument",
    signal_value: str = "signal",
    label_value: str = "forward_return",
    min_observations: int = 3,
    group_available_time: str | None = None,
    null_policy: Literal["drop", "raise"] = "drop",
    use_native: bool = True,
) -> AnalysisResult:
    """Compute per-group Pearson or average-rank Spearman information coefficients."""

    if method not in {"pearson", "spearman"}:
        raise MethodContractError("method must be 'pearson' or 'spearman'")
    if min_observations < 2:
        raise MethodContractError("min_observations must be at least 2")
    normalized_by = _normalized_group_request(by, signal_time=signal_time)
    extra_columns = [key for key in normalized_by if key not in {"observation_time", "horizon"}]
    if group_available_time is not None:
        extra_columns.append(group_available_time)
    panel, signal_diagnostics, label_diagnostics, excluded, signal_rows, matched = _aligned_panel(
        signal,
        labels,
        signal_time=signal_time,
        label_time=label_time,
        instrument=instrument,
        signal_value=signal_value,
        label_value=label_value,
        null_policy=null_policy,
        extra_signal_columns=tuple(dict.fromkeys(extra_columns)),
    )
    keys = _group_keys(panel, normalized_by)
    availability_findings = _group_availability_findings(
        panel,
        keys=keys,
        available_time=group_available_time,
    )
    group_sizes = (
        panel.group_by(keys, maintain_order=True).len(name="_group_size")
        if keys
        else pl.DataFrame({"_group_size": [panel.height]})
    )
    eligible_sizes = group_sizes.filter(pl.col("_group_size") >= min_observations)
    if eligible_sizes.is_empty():
        raise DataContractError(
            f"no groups contain the required {min_observations} aligned observations"
        )
    if keys:
        panel = panel.join(eligible_sizes.select(keys), on=keys, how="inner")

    def compute(source: pl.DataFrame, group_keys: Sequence[str]) -> pl.DataFrame:
        if method == "spearman" and use_native:
            try:
                return _native_grouped_rank_ic(source, group_keys)
            except (ImportError, AttributeError):
                return _reference_grouped_ic(source, group_keys, method)
        return _reference_grouped_ic(source, group_keys, method)

    backend = "numpy_reference"
    if method == "spearman" and use_native:
        try:
            period_ic = _native_grouped_rank_ic(panel, keys)
            backend = "rust_native"
        except (ImportError, AttributeError):
            period_ic = _reference_grouped_ic(panel, keys, method)
    else:
        period_ic = _reference_grouped_ic(panel, keys, method)

    period_ic = period_ic.sort(keys) if keys else period_ic
    overall_keys = [key for key in keys if key in {"observation_time", "horizon"}]
    overall_period_ic = compute(panel, overall_keys) if overall_keys != keys else period_ic
    overall_period_ic = overall_period_ic.sort(overall_keys) if overall_keys else overall_period_ic
    defined = period_ic.filter(pl.col("ic").is_not_null())
    overall_defined = overall_period_ic.filter(pl.col("ic").is_not_null())
    values = overall_defined.get_column("ic").to_list()
    metrics = _ic_metrics(values, int(overall_period_ic.get_column("n_observations").sum()))
    undefined_count = period_ic.height - defined.height
    undersized_count = group_sizes.height - eligible_sizes.height
    findings: list[Finding] = list(availability_findings)
    if undefined_count:
        findings.append(
            Finding(
                code="IC_UNDEFINED_GROUPS",
                title="Some IC groups are undefined",
                message="Groups with constant signal or label ranks cannot produce a correlation.",
                state=FindingState.WARN,
                severity=Severity.MEDIUM,
                category="statistical_validity",
                evidence={"undefined_groups": undefined_count},
            )
        )
    if undersized_count:
        findings.append(
            Finding(
                code="IC_UNDERSIZED_GROUPS",
                title="Undersized IC groups were excluded",
                message="Groups below the configured minimum observation count were not evaluated.",
                state=FindingState.WARN,
                severity=Severity.LOW,
                category="statistical_validity",
                evidence={"excluded_groups": undersized_count, "minimum": min_observations},
            )
        )
    if overall_defined.height < 20:
        findings.append(
            Finding(
                code="IC_PERIOD_SUPPORT_LOW",
                title="IC time-series support is limited",
                message="Fewer than 20 defined IC periods make aggregate inference fragile.",
                state=FindingState.WARN,
                severity=Severity.MEDIUM,
                category="statistical_validity",
                evidence={"n_periods": metrics["n_periods"]},
            )
        )

    group_eligible_rows = panel.height
    attrition: tuple[JsonValue, ...] = (
        attrition_record(
            "numeric_policy",
            "null_or_nan_signal_or_label",
            input_rows=matched,
            retained_rows=matched - excluded,
            policy=null_policy,
        ),
        attrition_record(
            "group_eligibility",
            "below_minimum_observations",
            input_rows=matched - excluded,
            retained_rows=group_eligible_rows,
            policy="drop",
        ),
    )
    tables: dict[str, JsonValue] = {
        "ic_by_period": frame_records(period_ic),
        "data_attrition": attrition,
    }
    if overall_keys != keys:
        tables["ic_overall_by_period"] = frame_records(overall_period_ic)
    horizon_summary = _horizon_summary(period_ic)
    if not horizon_summary.is_empty():
        tables["ic_by_horizon"] = frame_records(horizon_summary)
    if overall_keys != keys:
        overall_horizon_summary = _horizon_summary(overall_period_ic)
        if not overall_horizon_summary.is_empty():
            tables["ic_overall_by_horizon"] = frame_records(overall_horizon_summary)
    return AnalysisResult(
        metadata=ResultMetadata(
            method=f"signal.ic.{method}",
            method_version=1,
            parameters={
                "method": method,
                "by": tuple(keys),
                "group_available_time": group_available_time,
                "tie_policy": "average" if method == "spearman" else None,
                "minimum_observations": min_observations,
                "null_policy": null_policy,
                "backend": backend,
                "signal_input": signal_diagnostics.to_parameters(),
                "label_input": label_diagnostics.to_parameters(),
            },
        ),
        metrics={
            **metrics,
            "signal_rows": signal_rows,
            "matched_rows_before_policy": matched,
            "excluded_rows": excluded,
            "undefined_groups": undefined_count,
        },
        findings=tuple(findings),
        tables=tables,
        warnings=(
            "The reported t-statistic is the ordinary time-series statistic and does not "
            "adjust for serial dependence.",
        ),
    )


def _bucket_tables(
    panel: pl.DataFrame,
    *,
    keys: Sequence[str],
    top_bucket: int,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    working = panel.with_columns(pl.lit(0).alias("_single_group")) if not keys else panel
    effective_keys = ["_single_group"] if not keys else list(keys)
    period_bucket = (
        working.group_by([*effective_keys, "bucket"], maintain_order=True)
        .agg(
            pl.col("forward_return").mean().alias("mean_return"),
            pl.col("forward_return").median().alias("median_return"),
            pl.len().alias("n_observations"),
        )
        .sort([*effective_keys, "bucket"])
    )
    spread = (
        period_bucket.group_by(effective_keys, maintain_order=True)
        .agg(
            pl.col("mean_return")
            .filter(pl.col("bucket") == top_bucket)
            .first()
            .alias("top_return"),
            pl.col("mean_return").filter(pl.col("bucket") == 1).first().alias("bottom_return"),
        )
        .with_columns((pl.col("top_return") - pl.col("bottom_return")).alias("spread"))
    )
    summary_keys = [
        key for key in effective_keys if key not in {"observation_time", "_single_group"}
    ]
    summary_group_keys = [*summary_keys, "bucket"]
    bucket_summary = (
        period_bucket.group_by(summary_group_keys, maintain_order=True)
        .agg(
            pl.col("mean_return").mean().alias("mean_return"),
            pl.col("median_return").median().alias("median_return"),
            pl.col("n_observations").sum().alias("n_observations"),
            pl.len().alias("n_periods"),
        )
        .sort(summary_group_keys)
    )
    monotonicity_group_keys = summary_keys or ["_summary_group"]
    monotonicity_input = (
        bucket_summary.with_columns(pl.lit(0).alias("_summary_group"))
        if not summary_keys
        else bucket_summary
    )
    records: list[dict[str, object]] = []
    for group in monotonicity_input.partition_by(monotonicity_group_keys, maintain_order=True):
        ordered = group.sort("bucket")
        means: FloatArray = (
            ordered.get_column("mean_return").to_numpy().astype(np.float64, copy=False)
        )
        buckets: FloatArray = ordered.get_column("bucket").to_numpy().astype(np.float64, copy=False)
        differences = np.diff(means)
        record = {
            key: ordered.get_column(key)[0]
            for key in monotonicity_group_keys
            if key != "_summary_group"
        }
        record.update(
            {
                "spearman_monotonicity": _correlation(buckets, means, "spearman"),
                "adjacent_order_fraction": (
                    float(np.mean(differences > 0.0)) if differences.size else None
                ),
                "n_buckets": ordered.height,
            }
        )
        records.append(record)
    monotonicity = pl.DataFrame(records)
    for table in (period_bucket, spread, bucket_summary, monotonicity):
        if "_single_group" in table.columns:
            table.drop_in_place("_single_group")
    return period_bucket, spread, bucket_summary, monotonicity


def bucket_returns(
    bucketed: SignalTransformResult,
    labels: object,
    *,
    by: str | Sequence[str] | None = "observation_time",
    label_time: str = "observation_time",
    instrument: str = "instrument",
    label_value: str = "forward_return",
    null_policy: Literal["drop", "raise"] = "drop",
) -> AnalysisResult:
    """Summarize forward returns for an explicit bucket transformation."""

    if not isinstance(bucketed, SignalTransformResult):
        raise MethodContractError("bucketed must be a SignalTransformResult")
    if bucketed.metadata.method != "signal.bucketize":
        raise MethodContractError("bucketed must come from signal.bucketize")
    normalized_by = _normalized_group_request(by, signal_time="observation_time")
    extra_columns = [key for key in normalized_by if key not in {"observation_time", "horizon"}]
    extra_columns.append("bucket")
    panel, signal_diagnostics, label_diagnostics, excluded, signal_rows, matched = _aligned_panel(
        bucketed.frame,
        labels,
        signal_time="observation_time",
        label_time=label_time,
        instrument=instrument,
        signal_value="signal",
        label_value=label_value,
        null_policy=null_policy,
        extra_signal_columns=tuple(dict.fromkeys(extra_columns)),
    )
    if not panel.schema["bucket"].is_integer():
        raise DataContractError("bucket assignments must use an integer dtype")
    if panel.filter(pl.col("bucket") < 1).height:
        raise DataContractError("bucket assignments must be positive integers")
    requested = bucketed.evidence.metrics.get("requested_buckets")
    if not isinstance(requested, int):
        raise DataContractError("bucket evidence does not declare requested_buckets")
    keys = _group_keys(panel, normalized_by)
    period, spread, summary, monotonicity = _bucket_tables(panel, keys=keys, top_bucket=requested)
    overall_keys = [key for key in keys if key in {"observation_time", "horizon"}]
    if overall_keys != keys:
        overall_period, overall_spread, overall_summary, overall_monotonicity = _bucket_tables(
            panel, keys=overall_keys, top_bucket=requested
        )
    else:
        overall_period, overall_spread = period, spread
        overall_summary, overall_monotonicity = summary, monotonicity
    mean_spread = _float_or_none(overall_spread.get_column("spread").drop_nulls().mean())
    overall_record = overall_monotonicity.row(0, named=True)
    findings = list(bucketed.evidence.findings)
    monotonicity_value = _float_or_none(overall_record.get("spearman_monotonicity"))
    if monotonicity_value is not None and monotonicity_value < 0.5:
        findings.append(
            Finding(
                code="BUCKET_MONOTONICITY_WEAK",
                title="Bucket ordering is weak",
                message="Average bucket returns are not strongly ordered with the signal.",
                state=FindingState.WARN,
                severity=Severity.MEDIUM,
                category="statistical_validity",
                evidence={"spearman_monotonicity": monotonicity_value},
            )
        )
    attrition: tuple[JsonValue, ...] = (
        attrition_record(
            "numeric_policy",
            "null_or_nan_signal_or_label",
            input_rows=matched,
            retained_rows=matched - excluded,
            policy=null_policy,
        ),
    )
    tables: dict[str, JsonValue] = {
        "bucket_returns": frame_records(summary),
        "bucket_returns_by_period": frame_records(period),
        "bucket_spread_by_period": frame_records(spread),
        "bucket_monotonicity": frame_records(monotonicity),
        "data_attrition": attrition,
    }
    if overall_keys != keys:
        tables.update(
            {
                "bucket_overall_returns": frame_records(overall_summary),
                "bucket_overall_returns_by_period": frame_records(overall_period),
                "bucket_overall_spread_by_period": frame_records(overall_spread),
                "bucket_overall_monotonicity": frame_records(overall_monotonicity),
            }
        )
    return AnalysisResult(
        metadata=ResultMetadata(
            method="signal.bucket_returns",
            method_version=1,
            parameters={
                "by": tuple(keys),
                "bucket_method": bucketed.metadata.method,
                "bucket_method_version": bucketed.metadata.method_version,
                "bucket_spec": bucketed.metadata.parameters.get("spec"),
                "null_policy": null_policy,
                "signal_input": signal_diagnostics.to_parameters(),
                "label_input": label_diagnostics.to_parameters(),
            },
        ),
        metrics={
            "mean_top_bottom_spread": mean_spread,
            "spearman_monotonicity": monotonicity_value,
            "adjacent_order_fraction": overall_record.get("adjacent_order_fraction"),
            "n_buckets": requested,
            "n_observations": panel.height,
            "signal_rows": signal_rows,
            "matched_rows_before_policy": matched,
            "excluded_rows": excluded,
        },
        findings=tuple(findings),
        tables=tables,
    )


def _quantile_table(table: object) -> tuple[JsonValue, ...]:
    if not isinstance(table, list):
        raise TypeError("quantile compatibility table must contain row records")
    records: list[JsonValue] = []
    for row in table:
        if not isinstance(row, Mapping):
            raise TypeError("quantile compatibility table rows must be mappings")
        normalized = dict(row)
        if "bucket" in normalized:
            normalized["quantile"] = normalized.pop("bucket")
        if "n_buckets" in normalized:
            normalized["n_quantiles"] = normalized.pop("n_buckets")
        records.append(normalized)
    return tuple(records)


def quantiles(
    signal: object,
    labels: object,
    *,
    quantiles: int = 10,
    by: str | Sequence[str] | None = "observation_time",
    signal_time: str = "time",
    label_time: str = "observation_time",
    instrument: str = "instrument",
    signal_value: str = "signal",
    label_value: str = "forward_return",
    ascending: bool = True,
    tie_policy: Literal["balanced"] = "balanced",
    group_available_time: str | None = None,
    null_policy: Literal["drop", "raise"] = "drop",
) -> AnalysisResult:
    """Assign deterministic balanced quantiles and summarize subsequent returns."""

    if quantiles < 2:
        raise MethodContractError("quantiles must be at least 2")
    if tie_policy != "balanced":
        raise MethodContractError("v0.1 supports tie_policy='balanced'")
    normalized_by = _normalized_group_request(by, signal_time=signal_time)
    bucket_by: str | Sequence[str] = (
        tuple(signal_time if key == "observation_time" else key for key in normalized_by)
        or signal_time
    )
    bucketed = bucketize(
        signal,
        spec=BucketSpec.quantiles(quantiles, tie_policy=tie_policy),
        by=bucket_by,
        time=signal_time,
        instrument=instrument,
        signal_value=signal_value,
        available_time=group_available_time,
        ascending=ascending,
        small_group_policy="drop",
        null_policy=null_policy,
    )
    result = bucket_returns(
        bucketed,
        labels,
        by=normalized_by,
        label_time=label_time,
        instrument=instrument,
        label_value=label_value,
        null_policy=null_policy,
    )
    findings: list[Finding] = []
    for finding in result.findings:
        if finding.code == "BUCKET_UNDERSIZED_GROUPS":
            findings.append(
                Finding(
                    code="QUANTILE_UNDERSIZED_GROUPS",
                    title="Undersized quantile groups were excluded",
                    message=(
                        "Groups with fewer observations than requested quantiles were excluded."
                    ),
                    state=finding.state,
                    severity=finding.severity,
                    category=finding.category,
                    evidence={**finding.evidence, "quantiles": quantiles},
                )
            )
        elif finding.code == "BUCKET_MONOTONICITY_WEAK":
            findings.append(
                Finding(
                    code="QUANTILE_MONOTONICITY_WEAK",
                    title="Quantile ordering is weak",
                    message="Average quantile returns are not strongly ordered with the signal.",
                    state=finding.state,
                    severity=finding.severity,
                    category=finding.category,
                    evidence=finding.evidence,
                )
            )
        else:
            findings.append(finding)
    metrics: dict[str, JsonValue] = {
        **result.metrics,
        "n_quantiles": quantiles,
        "excluded_undersized_groups": bucketed.evidence.metrics.get("excluded_groups", 0),
    }
    metrics.pop("n_buckets", None)
    return AnalysisResult(
        metadata=ResultMetadata(
            method="signal.quantiles",
            method_version=1,
            parameters={
                "quantiles": quantiles,
                "by": normalized_by,
                "ascending": ascending,
                "tie_policy": tie_policy,
                "small_group_policy": "drop",
                "group_available_time": group_available_time,
                "null_policy": null_policy,
                "signal_input": bucketed.metadata.parameters.get("input"),
                "label_input": result.metadata.parameters.get("label_input"),
            },
        ),
        metrics=metrics,
        findings=tuple(findings),
        tables={
            "quantile_returns": _quantile_table(result.table("bucket_returns")),
            "quantile_returns_by_period": _quantile_table(result.table("bucket_returns_by_period")),
            "spread_by_period": _quantile_table(result.table("bucket_spread_by_period")),
            "monotonicity": _quantile_table(result.table("bucket_monotonicity")),
            "data_attrition": result.tables["data_attrition"],
        },
    )


def _signal_frame(
    signal: object,
    *,
    time: str,
    instrument: str,
    value: str,
    null_policy: Literal["drop", "raise"],
) -> tuple[pl.DataFrame, FrameDiagnostics, int]:
    frame, diagnostics = eager_frame(signal, required=[time, instrument, value])
    validate_panel_schema(
        frame,
        time=time,
        instrument=instrument,
        numeric=[value],
        name="signal",
    )
    diagnostics = diagnostics.with_execution(
        "validate_signal_frame",
        "project_and_cast_float64",
        "sort_and_group_signal_panel",
    )
    frame = frame.select(
        pl.col(time).alias("observation_time"),
        pl.col(instrument).alias("instrument"),
        pl.col(value).cast(pl.Float64).alias("signal"),
    )
    frame, excluded = paired_numeric_policy(frame, ["signal"], null_policy=null_policy)
    if frame.is_empty():
        raise DataContractError("signal has no finite observations")
    return frame, diagnostics, excluded


def turnover(
    signal: object,
    *,
    time: str = "time",
    instrument: str = "instrument",
    signal_value: str = "signal",
    quantiles: int = 5,
    lags: Sequence[int] = (1,),
    null_policy: Literal["drop", "raise"] = "drop",
) -> AnalysisResult:
    """Measure exact observation-lag rank, signal, and membership turnover."""

    if quantiles < 2:
        raise MethodContractError("quantiles must be at least 2")
    normalized_lags = tuple(lags)
    if (
        not normalized_lags
        or 1 not in normalized_lags
        or len(set(normalized_lags)) != len(normalized_lags)
        or any(
            isinstance(lag, bool) or not isinstance(lag, int) or lag < 1 for lag in normalized_lags
        )
    ):
        raise MethodContractError("lags must contain unique positive integers including 1")
    normalized_lags = tuple(sorted(normalized_lags))
    frame, diagnostics, excluded = _signal_frame(
        signal,
        time=time,
        instrument=instrument,
        value=signal_value,
        null_policy=null_policy,
    )
    periods = (
        frame.select("observation_time")
        .unique()
        .sort("observation_time")
        .with_row_index("_period_index")
    )
    if periods.height < 2:
        raise DataContractError("turnover requires at least two distinct observation periods")
    full_ranked = (
        frame.join(periods, on="observation_time", how="left")
        .sort(["observation_time", "signal", "instrument"])
        .with_columns(
            (
                (pl.col("signal").rank(method="average").over("observation_time") - 1)
                / (pl.len().over("observation_time") - 1).clip(lower_bound=1)
            ).alias("rank_fraction"),
            pl.col("signal").rank(method="ordinal").over("observation_time").alias("_ordinal"),
            pl.len().over("observation_time").alias("_period_count"),
        )
        .with_columns(
            (
                ((pl.col("_ordinal") - 1) * quantiles / pl.col("_period_count"))
                .floor()
                .cast(pl.Int32)
                + 1
            ).alias("quantile")
        )
    )
    transition_frames: list[pl.DataFrame] = []
    membership_frames: list[pl.DataFrame] = []
    membership_base = full_ranked.select(
        "_period_index",
        "observation_time",
        "instrument",
        pl.col("quantile").alias("bucket"),
    )
    membership_sizes = membership_base.group_by(
        ["_period_index", "bucket"], maintain_order=True
    ).len(name="_current_size")
    bucket_grid = pl.DataFrame({"bucket": np.arange(1, quantiles + 1, dtype=np.int32)})
    for lag in normalized_lags:
        previous = full_ranked.select(
            "instrument",
            (pl.col("_period_index") + lag).alias("_period_index"),
            pl.col("observation_time").alias("previous_observation_time"),
            pl.col("rank_fraction").alias("_previous_rank"),
            pl.col("signal").alias("_previous_signal"),
        )
        ranked = full_ranked.join(
            previous,
            on=["instrument", "_period_index"],
            how="inner",
        )
        if ranked.is_empty():
            raise DataContractError(f"no instruments occur at exact turnover lag {lag}")
        transitions = (
            ranked.group_by(
                ["_period_index", "previous_observation_time", "observation_time"],
                maintain_order=True,
            )
            .agg(
                (pl.col("rank_fraction") - pl.col("_previous_rank"))
                .abs()
                .mean()
                .alias("rank_turnover"),
                pl.corr("signal", "_previous_signal").alias("signal_autocorrelation"),
                pl.len().alias("n_common_instruments"),
            )
            .with_columns(
                pl.lit(lag).cast(pl.Int32).alias("lag"),
            )
            .sort("_period_index")
        )
        transition_frames.append(transitions)
        prior_membership = membership_base.select(
            (pl.col("_period_index") + lag).alias("_period_index"),
            "instrument",
            "bucket",
        )
        intersections = (
            membership_base.join(
                prior_membership,
                on=["_period_index", "instrument", "bucket"],
                how="inner",
            )
            .group_by(["_period_index", "bucket"], maintain_order=True)
            .len(name="_intersection_size")
        )
        previous_sizes = membership_sizes.select(
            (pl.col("_period_index") + lag).alias("_period_index"),
            "bucket",
            pl.col("_current_size").alias("_previous_size"),
        )
        endpoint_grid = (
            periods.filter(pl.col("_period_index") >= lag)
            .join(
                periods.select(
                    (pl.col("_period_index") + lag).alias("_period_index"),
                    pl.col("observation_time").alias("previous_observation_time"),
                ),
                on="_period_index",
                how="inner",
            )
            .join(bucket_grid, how="cross")
            .join(membership_sizes, on=["_period_index", "bucket"], how="left")
            .join(previous_sizes, on=["_period_index", "bucket"], how="left")
            .join(intersections, on=["_period_index", "bucket"], how="left")
            .with_columns(
                pl.col("_current_size").fill_null(0),
                pl.col("_previous_size").fill_null(0),
                pl.col("_intersection_size").fill_null(0),
            )
        )
        membership_denominator = pl.col("_previous_size") + pl.col("_current_size")
        membership_frames.append(
            endpoint_grid.with_columns(
                pl.lit(lag).cast(pl.Int32).alias("lag"),
                pl.when(membership_denominator > 0)
                .then(
                    (membership_denominator - 2 * pl.col("_intersection_size"))
                    / membership_denominator
                )
                .otherwise(None)
                .alias("membership_turnover"),
            ).select(
                "_period_index",
                "lag",
                "previous_observation_time",
                "observation_time",
                "bucket",
                "membership_turnover",
            )
        )
    transitions_by_lag = pl.concat(transition_frames, how="vertical").sort(["lag", "_period_index"])
    membership = pl.concat(membership_frames, how="vertical").sort(
        ["lag", "_period_index", "bucket"]
    )
    tails = membership.group_by(["lag", "_period_index"], maintain_order=True).agg(
        pl.col("membership_turnover")
        .filter(pl.col("bucket") == quantiles)
        .first()
        .alias("top_membership_turnover"),
        pl.col("membership_turnover")
        .filter(pl.col("bucket") == 1)
        .first()
        .alias("bottom_membership_turnover"),
    )
    transitions_by_lag = transitions_by_lag.join(tails, on=["lag", "_period_index"], how="left")
    legacy = (
        transitions_by_lag.filter(pl.col("lag") == 1)
        .select(
            "observation_time",
            "rank_turnover",
            "signal_autocorrelation",
            "n_common_instruments",
            "top_membership_turnover",
            "bottom_membership_turnover",
        )
        .sort("observation_time")
    )
    summary = (
        transitions_by_lag.group_by("lag", maintain_order=True)
        .agg(
            pl.col("rank_turnover").mean().alias("mean_rank_turnover"),
            pl.col("signal_autocorrelation")
            .drop_nulls()
            .mean()
            .alias("mean_signal_autocorrelation"),
            pl.col("top_membership_turnover")
            .drop_nulls()
            .mean()
            .alias("mean_top_membership_turnover"),
            pl.col("bottom_membership_turnover")
            .drop_nulls()
            .mean()
            .alias("mean_bottom_membership_turnover"),
            pl.len().alias("n_transitions"),
        )
        .sort("lag")
    )
    mean_rank_turnover = _float_or_none(legacy.get_column("rank_turnover").mean())
    mean_autocorrelation = _float_or_none(
        legacy.get_column("signal_autocorrelation").drop_nulls().mean()
    )
    attrition: tuple[JsonValue, ...] = (
        attrition_record(
            "numeric_policy",
            "null_or_nan_signal",
            input_rows=diagnostics.rows,
            retained_rows=frame.height,
            policy=null_policy,
        ),
    )
    return AnalysisResult(
        metadata=ResultMetadata(
            method="signal.turnover",
            method_version=1,
            parameters={
                "rank_turnover_definition": "mean absolute percentile-rank change",
                "membership_turnover_definition": "symmetric difference / total membership",
                "quantiles": quantiles,
                "lags": normalized_lags,
                "lag_clock": "global_observation_index",
                "null_policy": null_policy,
                "input": diagnostics.to_parameters(),
            },
        ),
        metrics={
            "mean_rank_turnover": mean_rank_turnover,
            "mean_signal_autocorrelation": mean_autocorrelation,
            "n_transitions": legacy.height,
            "n_observations": frame.height,
            "excluded_rows": excluded,
        },
        tables={
            "turnover_by_period": frame_records(legacy),
            "turnover_by_period_lag": frame_records(transitions_by_lag.drop("_period_index")),
            "turnover_by_lag": frame_records(summary),
            "membership_turnover_by_period_lag": frame_records(membership.drop("_period_index")),
            "data_attrition": attrition,
        },
    )


def decay(
    signal: object,
    labels_or_prices: object,
    *,
    horizons: Sequence[Horizon] | None = None,
    signal_time: str = "time",
    instrument: str = "instrument",
    signal_value: str = "signal",
    price_time: str = "time",
    price: str = "close",
    entry: str | None = None,
    price_adjustment: str = "unknown",
    min_observations: int = 3,
    quantile_count: int = 5,
    use_native: bool = True,
) -> AnalysisResult:
    """Evaluate IC and top-bottom spread over explicit label horizons."""

    if isinstance(labels_or_prices, LabelResult):
        if horizons is not None:
            raise MethodContractError("horizons are already defined by the LabelResult")
        labels: object = labels_or_prices
    else:
        candidate, _ = eager_frame(labels_or_prices)
        if "forward_return" in candidate.columns:
            if horizons is not None:
                raise MethodContractError("horizons cannot be supplied with a label frame")
            labels = candidate
        else:
            if horizons is None:
                raise MethodContractError("horizons are required when decay receives prices")
            labels = forward_returns(
                candidate,
                horizons=horizons,
                time=price_time,
                instrument=instrument,
                price=price,
                entry=entry,
                price_adjustment=price_adjustment,  # type: ignore[arg-type]
            )
    ic_result = ic(
        signal,
        labels,
        method="spearman",
        signal_time=signal_time,
        instrument=instrument,
        signal_value=signal_value,
        min_observations=min_observations,
        use_native=use_native,
    )
    quantile_result = quantiles(
        signal,
        labels,
        quantiles=quantile_count,
        signal_time=signal_time,
        instrument=instrument,
        signal_value=signal_value,
    )
    ic_records = cast(Sequence[Mapping[str, object]], ic_result.table("ic_by_horizon"))
    spread_records = cast(Sequence[Mapping[str, object]], quantile_result.table("spread_by_period"))
    ic_by_horizon = pl.DataFrame(ic_records)
    spread_by_period = pl.DataFrame(spread_records)
    if "horizon" not in spread_by_period.columns:
        raise DataContractError("decay requires labels with a horizon column")
    spread_by_horizon = spread_by_period.group_by("horizon", maintain_order=True).agg(
        pl.col("spread").mean().alias("mean_top_bottom_spread"),
        pl.col("spread").std(ddof=1).alias("std_top_bottom_spread"),
        pl.len().alias("n_periods"),
    )
    decay_table = ic_by_horizon.join(
        spread_by_horizon, on="horizon", how="full", coalesce=True
    ).sort("horizon")
    return AnalysisResult(
        metadata=ResultMetadata(
            method="signal.decay",
            method_version=1,
            parameters={
                "ic_method": "spearman",
                "quantiles": quantile_count,
                "minimum_observations": min_observations,
                "half_life_policy": "not_estimated_in_v0.1",
            },
        ),
        metrics={
            "n_horizons": decay_table.height,
            "n_observations": ic_result.metrics["n_observations"],
        },
        findings=tuple((*ic_result.findings, *quantile_result.findings)),
        tables={
            "ic_decay": frame_records(decay_table),
            "ic_by_period_horizon": ic_result.tables["ic_by_period"],
            "spread_by_period_horizon": quantile_result.tables["spread_by_period"],
        },
        warnings=(
            "A half-life is not estimated unless a validated identifiable decay model is supplied.",
        ),
    )


__all__ = [
    "BucketSpec",
    "CorrelationMethod",
    "PortfolioProjectionResult",
    "SignalTransformResult",
    "bucket_returns",
    "bucketize",
    "decay",
    "fit_decay",
    "ic",
    "neutralize",
    "portfolio_projection",
    "quantiles",
    "turnover",
]
