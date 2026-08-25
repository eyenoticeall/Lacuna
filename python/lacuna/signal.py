"""Cross-sectional signal diagnostics."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from numbers import Real
from typing import Any, Literal, TypeAlias, cast

import numpy as np
import numpy.typing as npt
import polars as pl

from lacuna._frames import (
    FrameDiagnostics,
    eager_frame,
    frame_records,
    paired_numeric_policy,
    require_unique,
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
        materialized=False,
    )
    label_diagnostics = FrameDiagnostics(
        source_type="numpy.ndarray",
        rows=label_values.shape[0],
        columns=("forward_return",),
        materialized=False,
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
) -> tuple[pl.DataFrame, FrameDiagnostics, FrameDiagnostics, int, int, int]:
    if isinstance(signal_data, np.ndarray) and isinstance(labels, np.ndarray):
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
        required=[signal_time, instrument, signal_value],
    )
    label_source = labels.frame if isinstance(labels, LabelResult) else labels
    label_frame, label_diagnostics = eager_frame(
        label_source,
        required=[label_time, instrument, label_value],
    )
    if signal_frame.is_empty() or label_frame.is_empty():
        raise DataContractError("signal and labels must each contain at least one row")

    require_unique(signal_frame, [signal_time, instrument], name="signal")
    label_key = [label_time, instrument]
    if "horizon" in label_frame.columns:
        label_key.append("horizon")
    require_unique(label_frame, label_key, name="labels")

    signal_projection = signal_frame.select(
        pl.col(signal_time).alias("observation_time"),
        pl.col(instrument).alias("instrument"),
        pl.col(signal_value).cast(pl.Float64).alias("signal"),
    )
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
    counts = groups.get_column("n_observations").to_list()
    offsets = [0]
    for count in counts:
        offsets.append(offsets[-1] + int(count))
    correlations = _native.grouped_rank_ic(
        ordered.get_column("signal").to_list(),
        ordered.get_column("forward_return").to_list(),
        offsets,
    )
    result = groups.with_columns(pl.Series("ic", correlations, dtype=pl.Float64))
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
    return (
        period_ic.group_by("horizon", maintain_order=True)
        .agg(
            pl.col("ic").drop_nulls().mean().alias("mean_ic"),
            pl.col("ic").drop_nulls().median().alias("median_ic"),
            pl.col("ic").drop_nulls().std(ddof=1).alias("std_ic"),
            pl.col("ic").drop_nulls().len().alias("n_periods"),
            pl.col("n_observations").sum(),
        )
        .with_columns((pl.col("mean_ic") / pl.col("std_ic")).alias("ic_information_ratio"))
        .sort("horizon")
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
    null_policy: Literal["drop", "raise"] = "drop",
    use_native: bool = True,
) -> AnalysisResult:
    """Compute per-group Pearson or average-rank Spearman information coefficients."""

    if method not in {"pearson", "spearman"}:
        raise MethodContractError("method must be 'pearson' or 'spearman'")
    if min_observations < 2:
        raise MethodContractError("min_observations must be at least 2")
    panel, signal_diagnostics, label_diagnostics, excluded, signal_rows, matched = _aligned_panel(
        signal,
        labels,
        signal_time=signal_time,
        label_time=label_time,
        instrument=instrument,
        signal_value=signal_value,
        label_value=label_value,
        null_policy=null_policy,
    )
    keys = _group_keys(panel, by)
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
    defined = period_ic.filter(pl.col("ic").is_not_null())
    values = defined.get_column("ic").to_list()
    metrics = _ic_metrics(values, int(period_ic.get_column("n_observations").sum()))
    undefined_count = period_ic.height - defined.height
    undersized_count = group_sizes.height - eligible_sizes.height
    findings: list[Finding] = []
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
    if defined.height < 20:
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

    tables: dict[str, JsonValue] = {"ic_by_period": frame_records(period_ic)}
    horizon_summary = _horizon_summary(period_ic)
    if not horizon_summary.is_empty():
        tables["ic_by_horizon"] = frame_records(horizon_summary)
    return AnalysisResult(
        metadata=ResultMetadata(
            method=f"signal.ic.{method}",
            method_version=1,
            parameters={
                "method": method,
                "by": tuple(keys),
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
    null_policy: Literal["drop", "raise"] = "drop",
) -> AnalysisResult:
    """Assign deterministic balanced quantiles and summarize subsequent returns."""

    if quantiles < 2:
        raise MethodContractError("quantiles must be at least 2")
    if tie_policy != "balanced":
        raise MethodContractError("v0.1 supports tie_policy='balanced'")
    panel, signal_diagnostics, label_diagnostics, excluded, signal_rows, matched = _aligned_panel(
        signal,
        labels,
        signal_time=signal_time,
        label_time=label_time,
        instrument=instrument,
        signal_value=signal_value,
        label_value=label_value,
        null_policy=null_policy,
    )
    keys = _group_keys(panel, by)
    if not keys:
        panel = panel.with_columns(pl.lit(0).alias("_single_group"))
        keys = ["_single_group"]
    sizes = panel.group_by(keys, maintain_order=True).len(name="_group_size")
    eligible_sizes = sizes.filter(pl.col("_group_size") >= quantiles)
    if eligible_sizes.is_empty():
        raise DataContractError(
            f"no groups contain at least {quantiles} observations for quantile assignment"
        )
    eligible = panel.join(eligible_sizes.select(keys), on=keys, how="inner")
    sort_keys = [*keys, "signal", "instrument"]
    if not ascending:
        descending = [False] * len(keys) + [True, False]
        eligible = eligible.sort(sort_keys, descending=descending)
    else:
        eligible = eligible.sort(sort_keys)
    assigned = (
        eligible.with_columns(
            pl.col("signal").rank(method="ordinal").over(keys).alias("_ordinal"),
            pl.len().over(keys).alias("_count"),
        )
        .with_columns(
            (
                ((pl.col("_ordinal") - 1) * quantiles / pl.col("_count")).floor().cast(pl.Int32) + 1
            ).alias("quantile")
        )
        .drop("_ordinal", "_count")
    )
    period_quantile = (
        assigned.group_by([*keys, "quantile"], maintain_order=True)
        .agg(
            pl.col("forward_return").mean().alias("mean_return"),
            pl.col("forward_return").median().alias("median_return"),
            pl.len().alias("n_observations"),
        )
        .sort([*keys, "quantile"])
    )
    spread = (
        period_quantile.group_by(keys, maintain_order=True)
        .agg(
            pl.col("mean_return")
            .filter(pl.col("quantile") == quantiles)
            .first()
            .alias("top_return"),
            pl.col("mean_return").filter(pl.col("quantile") == 1).first().alias("bottom_return"),
        )
        .with_columns((pl.col("top_return") - pl.col("bottom_return")).alias("spread"))
    )

    summary_keys = [key for key in keys if key not in {"observation_time", "_single_group"}]
    summary_group_keys = [*summary_keys, "quantile"]
    quantile_summary = (
        period_quantile.group_by(summary_group_keys, maintain_order=True)
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
        quantile_summary.with_columns(pl.lit(0).alias("_summary_group"))
        if not summary_keys
        else quantile_summary
    )
    monotonicity_records: list[dict[str, object]] = []
    for group in monotonicity_input.partition_by(monotonicity_group_keys, maintain_order=True):
        ordered_group = group.sort("quantile")
        means: FloatArray = (
            ordered_group.get_column("mean_return").to_numpy().astype(np.float64, copy=False)
        )
        q_values: FloatArray = (
            ordered_group.get_column("quantile").to_numpy().astype(np.float64, copy=False)
        )
        diffs = np.diff(means)
        record = {
            key: ordered_group.get_column(key)[0]
            for key in monotonicity_group_keys
            if key != "_summary_group"
        }
        record.update(
            {
                "spearman_monotonicity": _correlation(q_values, means, "spearman"),
                "adjacent_order_fraction": float(np.mean(diffs > 0.0)) if diffs.size else None,
                "n_quantiles": ordered_group.height,
            }
        )
        monotonicity_records.append(record)
    monotonicity = pl.DataFrame(monotonicity_records)

    mean_spread = _float_or_none(spread.get_column("spread").drop_nulls().mean())
    first_monotonicity = monotonicity.row(0, named=True)
    undersized_groups = sizes.height - eligible_sizes.height
    findings: list[Finding] = []
    if undersized_groups:
        findings.append(
            Finding(
                code="QUANTILE_UNDERSIZED_GROUPS",
                title="Undersized quantile groups were excluded",
                message="Groups with fewer observations than requested quantiles were excluded.",
                state=FindingState.WARN,
                severity=Severity.MEDIUM,
                category="statistical_validity",
                evidence={"excluded_groups": undersized_groups, "quantiles": quantiles},
            )
        )
    if first_monotonicity.get("spearman_monotonicity") is not None:
        monotonicity_value = _float_or_none(first_monotonicity["spearman_monotonicity"])
        assert monotonicity_value is not None
        if monotonicity_value < 0.5:
            findings.append(
                Finding(
                    code="QUANTILE_MONOTONICITY_WEAK",
                    title="Quantile ordering is weak",
                    message="Average quantile returns are not strongly ordered with the signal.",
                    state=FindingState.WARN,
                    severity=Severity.MEDIUM,
                    category="statistical_validity",
                    evidence={"spearman_monotonicity": monotonicity_value},
                )
            )

    for table in (period_quantile, spread, quantile_summary, monotonicity):
        if "_single_group" in table.columns:
            table.drop_in_place("_single_group")
    metrics: dict[str, JsonValue] = {
        "mean_top_bottom_spread": mean_spread,
        "spearman_monotonicity": first_monotonicity.get("spearman_monotonicity"),
        "adjacent_order_fraction": first_monotonicity.get("adjacent_order_fraction"),
        "n_quantiles": quantiles,
        "n_observations": assigned.height,
        "signal_rows": signal_rows,
        "matched_rows_before_policy": matched,
        "excluded_rows": excluded,
        "excluded_undersized_groups": undersized_groups,
    }
    return AnalysisResult(
        metadata=ResultMetadata(
            method="signal.quantiles",
            method_version=1,
            parameters={
                "quantiles": quantiles,
                "by": tuple(key for key in keys if key != "_single_group"),
                "ascending": ascending,
                "tie_policy": tie_policy,
                "small_group_policy": "drop",
                "null_policy": null_policy,
                "signal_input": signal_diagnostics.to_parameters(),
                "label_input": label_diagnostics.to_parameters(),
            },
        ),
        metrics=metrics,
        findings=tuple(findings),
        tables={
            "quantile_returns": frame_records(quantile_summary),
            "quantile_returns_by_period": frame_records(period_quantile),
            "spread_by_period": frame_records(spread),
            "monotonicity": frame_records(monotonicity),
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
    require_unique(frame, [time, instrument], name="signal")
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
    null_policy: Literal["drop", "raise"] = "drop",
) -> AnalysisResult:
    """Measure consecutive-period rank, signal, and tail-membership turnover."""

    if quantiles < 2:
        raise MethodContractError("quantiles must be at least 2")
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
    ranked = (
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
        .sort(["instrument", "_period_index"])
        .with_columns(
            pl.col("_period_index").shift(1).over("instrument").alias("_previous_period"),
            pl.col("rank_fraction").shift(1).over("instrument").alias("_previous_rank"),
            pl.col("signal").shift(1).over("instrument").alias("_previous_signal"),
        )
        .filter(pl.col("_period_index") == pl.col("_previous_period") + 1)
    )
    if ranked.is_empty():
        raise DataContractError("no instruments occur in consecutive periods")
    transitions = (
        ranked.group_by(["_period_index", "observation_time"], maintain_order=True)
        .agg(
            (pl.col("rank_fraction") - pl.col("_previous_rank"))
            .abs()
            .mean()
            .alias("rank_turnover"),
            pl.corr("signal", "_previous_signal").alias("signal_autocorrelation"),
            pl.len().alias("n_common_instruments"),
        )
        .sort("_period_index")
    )

    full_ranked = (
        frame.join(periods, on="observation_time", how="left")
        .sort(["observation_time", "signal", "instrument"])
        .with_columns(
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
    tail_sets: dict[int, tuple[set[object], set[object]]] = {}
    for group in full_ranked.partition_by("_period_index", maintain_order=True):
        period_index = int(group.get_column("_period_index")[0])
        bottom = set(group.filter(pl.col("quantile") == 1).get_column("instrument").to_list())
        top = set(group.filter(pl.col("quantile") == quantiles).get_column("instrument").to_list())
        tail_sets[period_index] = (bottom, top)
    membership_rows: list[dict[str, object]] = []
    for period_index in range(1, periods.height):
        previous_bottom, previous_top = tail_sets.get(period_index - 1, (set(), set()))
        current_bottom, current_top = tail_sets.get(period_index, (set(), set()))

        def symmetric_turnover(previous: set[object], current: set[object]) -> float | None:
            denominator = len(previous) + len(current)
            return (
                len(previous.symmetric_difference(current)) / denominator if denominator else None
            )

        membership_rows.append(
            {
                "_period_index": period_index,
                "top_membership_turnover": symmetric_turnover(previous_top, current_top),
                "bottom_membership_turnover": symmetric_turnover(previous_bottom, current_bottom),
            }
        )
    membership = pl.DataFrame(membership_rows)
    transitions = transitions.join(membership, on="_period_index", how="left").drop("_period_index")
    mean_rank_turnover = _float_or_none(transitions.get_column("rank_turnover").mean())
    mean_autocorrelation = _float_or_none(
        transitions.get_column("signal_autocorrelation").drop_nulls().mean()
    )
    return AnalysisResult(
        metadata=ResultMetadata(
            method="signal.turnover",
            method_version=1,
            parameters={
                "rank_turnover_definition": "mean absolute percentile-rank change",
                "membership_turnover_definition": "symmetric difference / total membership",
                "quantiles": quantiles,
                "null_policy": null_policy,
                "input": diagnostics.to_parameters(),
            },
        ),
        metrics={
            "mean_rank_turnover": mean_rank_turnover,
            "mean_signal_autocorrelation": mean_autocorrelation,
            "n_transitions": transitions.height,
            "n_observations": frame.height,
            "excluded_rows": excluded,
        },
        tables={"turnover_by_period": frame_records(transitions)},
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
        tables={"ic_decay": frame_records(decay_table)},
        warnings=(
            "A half-life is not estimated unless a validated identifiable decay model is supplied.",
        ),
    )


__all__ = ["CorrelationMethod", "decay", "ic", "quantiles", "turnover"]
