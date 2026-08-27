"""Dependence-aware resampling for financial research evidence."""

from __future__ import annotations

import json
import math
import secrets
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from itertools import product
from numbers import Real
from typing import Literal, TypeAlias, cast

import numpy as np
import numpy.typing as npt
import polars as pl

from lacuna._advanced_inference import (
    PBOStatistic,
    PBOTieBreak,
    PermutationAlternative,
    PermutationScheme,
    PermutationStatistic,
    joint_stationary_bootstrap,
    permutation_test,
    probability_of_backtest_overfitting,
    reality_check,
    sharpe_inference,
    superior_predictive_ability,
)
from lacuna._carriers import ResampleBatch
from lacuna._execution import resolve_execution_budget
from lacuna._frames import (
    FrameDiagnostics,
    eager_frame,
    frame_records,
    paired_numeric_policy,
    require_identifier,
    require_no_nulls,
    require_numeric,
    require_unique,
)
from lacuna._native_arrays import readonly_float64, readonly_int64
from lacuna._resampling import indexed_column_means_reference
from lacuna.config import get_config
from lacuna.exceptions import DataContractError, MethodContractError
from lacuna.experiment import (
    AttemptStatus,
    ExperimentRegistry,
    canonical_json,
    fingerprint,
)
from lacuna.types import AnalysisResult, Finding, FindingState, JsonValue, ResultMetadata, Severity

FloatArray: TypeAlias = npt.NDArray[np.float64]
BootstrapMethod: TypeAlias = Literal["iid", "moving", "circular", "stationary"]
IntervalMethod: TypeAlias = Literal["percentile", "basic"]
Statistic: TypeAlias = Literal["mean", "median", "sharpe"] | Callable[[FloatArray], float]
MultipleTestingMethod: TypeAlias = Literal[
    "bonferroni",
    "holm",
    "benjamini_hochberg",
    "benjamini_yekutieli",
]
ObjectiveDirection: TypeAlias = Literal["maximize", "minimize"]
SurfaceFailurePolicy: TypeAlias = Literal["record", "raise"]


@dataclass(frozen=True, slots=True)
class _SurfacePoint:
    indices: tuple[int, ...]
    parameters: Mapping[str, JsonValue]
    point_id: str
    status: str
    objective: float | None
    error_category: str | None
    warnings: tuple[str, ...]


def _values_array(
    data: object,
    *,
    value: str,
    null_policy: Literal["drop", "raise"],
) -> tuple[FloatArray, dict[str, JsonValue], int]:
    if isinstance(data, np.ndarray):
        if data.ndim != 1:
            raise DataContractError("bootstrap NumPy input must be one-dimensional")
        frame = pl.DataFrame({value: data})
        diagnostics = FrameDiagnostics(
            source_type="numpy.ndarray",
            rows=int(data.shape[0]),
            columns=(value,),
            lazy_input=False,
            materialized=False,
            adapter_copy="potentially_zero_copy",
            adapter_operations=("numpy_to_polars",),
        )
    elif isinstance(data, Sequence) and not isinstance(data, str | bytes):
        frame = pl.DataFrame({value: data})
        diagnostics = FrameDiagnostics(
            source_type=f"{type(data).__module__}.{type(data).__name__}",
            rows=len(data),
            columns=(value,),
            lazy_input=False,
            materialized=False,
            adapter_copy="one_copy",
            adapter_operations=("sequence_to_polars",),
        )
    else:
        frame, diagnostics = eager_frame(data, required=[value])
    diagnostics = diagnostics.with_execution("project_and_cast_float64")
    source: dict[str, JsonValue] = diagnostics.to_parameters()
    frame = frame.select(pl.col(value).cast(pl.Float64).alias("value"))
    frame, excluded = paired_numeric_policy(frame, ["value"], null_policy=null_policy)
    if frame.height < 2:
        raise DataContractError("bootstrap requires at least two finite observations")
    values: FloatArray = frame.get_column("value").to_numpy().astype(np.float64, copy=False)
    return values, source, excluded


def _statistic_function(statistic: Statistic) -> tuple[str, Callable[[FloatArray], float]]:
    if callable(statistic):
        name = getattr(statistic, "__name__", "custom")

        def custom(values: FloatArray) -> float:
            return float(statistic(values))

        return name, custom
    if statistic == "mean":
        return "mean", lambda values: float(values.mean())
    if statistic == "median":
        return "median", lambda values: float(np.median(values))
    if statistic == "sharpe":

        def sharpe(values: FloatArray) -> float:
            standard_deviation = float(values.std(ddof=1))
            if standard_deviation == 0.0:
                raise DataContractError("Sharpe statistic is undefined for zero-variance samples")
            return float(values.mean()) / standard_deviation

        return "sharpe", sharpe
    raise MethodContractError("statistic must be 'mean', 'median', 'sharpe', or a callable")


def _replicate_rng(seed: int, replicate: int) -> np.random.Generator:
    return np.random.default_rng(np.random.SeedSequence([seed, 1, replicate]))


def _bootstrap_indices(
    *,
    size: int,
    method: BootstrapMethod,
    block_length: int,
    seed: int,
    replicate: int,
) -> npt.NDArray[np.intp]:
    rng = _replicate_rng(seed, replicate)
    if method == "iid":
        return rng.integers(0, size, size=size, dtype=np.intp)
    if method == "stationary":
        probability = 1.0 / block_length
        blocks: list[npt.NDArray[np.intp]] = []
        remaining = size
        while remaining:
            length = min(int(rng.geometric(probability)), remaining)
            start = int(rng.integers(0, size))
            blocks.append((start + np.arange(length, dtype=np.intp)) % size)
            remaining -= length
        return np.concatenate(blocks)

    block_count = math.ceil(size / block_length)
    if method == "moving":
        maximum_start = size - block_length
        starts = rng.integers(0, maximum_start + 1, size=block_count, dtype=np.intp)
        indices = np.concatenate(
            [np.arange(start, start + block_length, dtype=np.intp) for start in starts]
        )
    else:
        starts = rng.integers(0, size, size=block_count, dtype=np.intp)
        offsets: npt.NDArray[np.intp] = np.arange(block_length, dtype=np.intp)
        indices = np.concatenate([(start + offsets) % size for start in starts])
    return indices[:size]


def _native_mean_batch(
    batch: ResampleBatch,
) -> FloatArray | None:
    try:
        from lacuna import _native
    except ImportError:
        return None
    if not hasattr(_native, "bootstrap_means"):
        return None
    native_values = readonly_float64(batch.values[:, 0], name="values").values
    native_indices = readonly_int64(batch.indices, name="indices").values
    native_offsets = readonly_int64(batch.offsets, name="offsets").values
    return _native.bootstrap_means(native_values, native_indices, native_offsets)


def _distribution_summary(distribution: FloatArray) -> pl.DataFrame:
    probabilities = np.asarray([0.0, 0.01, 0.025, 0.05, 0.25, 0.5, 0.75, 0.95, 0.975, 0.99, 1.0])
    values = np.quantile(distribution, probabilities)
    return pl.DataFrame(
        {
            "probability": probabilities,
            "value": values,
        }
    )


def bootstrap(
    data: object,
    *,
    value: str = "value",
    statistic: Statistic = "mean",
    method: BootstrapMethod = "moving",
    block_length: int | None = None,
    expected_block_length: int | None = None,
    resamples: int = 1_000,
    confidence_level: float = 0.95,
    interval: IntervalMethod = "percentile",
    seed: int | None = None,
    null_policy: Literal["drop", "raise"] = "drop",
    store_distribution: bool = False,
    use_native: bool = True,
    batch_memory_bytes: int = 16 * 1024 * 1024,
) -> AnalysisResult:
    """Estimate a statistic and confidence interval with deterministic resampling.

    Moving, circular, and stationary methods preserve local dependence. Each
    replicate derives its random stream from ``(seed, method_version, index)``.
    """

    if method not in {"iid", "moving", "circular", "stationary"}:
        raise MethodContractError("method must be 'iid', 'moving', 'circular', or 'stationary'")
    if interval not in {"percentile", "basic"}:
        raise MethodContractError("interval must be 'percentile' or 'basic'")
    if resamples < 100:
        raise MethodContractError("resamples must be at least 100 for inferential output")
    if not 0.0 < confidence_level < 1.0:
        raise MethodContractError("confidence_level must be between zero and one")
    if batch_memory_bytes < 1024:
        raise MethodContractError("batch_memory_bytes must be at least 1024")
    values, source, excluded = _values_array(data, value=value, null_policy=null_policy)
    statistic_name, statistic_function = _statistic_function(statistic)
    if expected_block_length is not None and block_length is not None:
        raise MethodContractError("pass block_length or expected_block_length, not both")
    if expected_block_length is not None and method != "stationary":
        raise MethodContractError("expected_block_length is only valid for stationary bootstrap")
    resolved_block_length = expected_block_length or block_length
    if method == "iid":
        if resolved_block_length is not None:
            raise MethodContractError("block length does not apply to IID bootstrap")
        resolved_block_length = 1
    elif resolved_block_length is None:
        resolved_block_length = max(2, round(values.size ** (1.0 / 3.0)))
    if resolved_block_length < 1 or resolved_block_length > values.size:
        raise MethodContractError("block length must be between 1 and the sample size")

    runtime_config = get_config()
    resolved_seed = seed if seed is not None else runtime_config.seed
    if resolved_seed is None:
        resolved_seed = secrets.randbits(63)
    if resolved_seed < 0:
        raise MethodContractError("seed must be non-negative")

    observed = statistic_function(values)
    if not math.isfinite(observed):
        raise DataContractError("observed statistic is not finite")
    bytes_per_resample = max(values.size * np.dtype(np.intp).itemsize, 1)
    execution_budget = resolve_execution_budget(
        total_items=resamples,
        required_fixed_allocation_bytes=resamples * np.dtype(np.float64).itemsize,
        per_item_workspace_bytes=bytes_per_resample,
        workspace_cap_bytes=batch_memory_bytes,
        backend="rust_native_candidate" if use_native and statistic_name == "mean" else "numpy",
        dispatch_reason=(
            "built-in mean requested native reduction"
            if use_native and statistic_name == "mean"
            else "reference or custom statistic requires Python/NumPy reduction"
        ),
        configuration=runtime_config,
    )
    batch_size = execution_budget.selected_batch_size
    distribution: FloatArray = np.empty(resamples, dtype=np.float64)
    backend = "numpy_reference"
    for batch_start in range(0, resamples, batch_size):
        batch_end = min(resamples, batch_start + batch_size)
        index_batch = [
            _bootstrap_indices(
                size=values.size,
                method=method,
                block_length=resolved_block_length,
                seed=resolved_seed,
                replicate=replicate,
            )
            for replicate in range(batch_start, batch_end)
        ]
        resample_batch = ResampleBatch.from_samples(values.reshape(-1, 1), index_batch)
        native_means = (
            _native_mean_batch(resample_batch) if statistic_name == "mean" and use_native else None
        )
        if native_means is not None:
            distribution[batch_start:batch_end] = native_means
            backend = "rust_native"
        else:
            if statistic_name == "mean":
                distribution[batch_start:batch_end] = indexed_column_means_reference(
                    resample_batch
                )[:, 0]
            else:
                distribution[batch_start:batch_end] = [
                    statistic_function(values[indices]) for indices in index_batch
                ]
    if not np.isfinite(distribution).all():
        raise DataContractError("one or more bootstrap replicates produced a non-finite statistic")

    alpha = 1.0 - confidence_level
    lower_quantile, upper_quantile = np.quantile(distribution, [alpha / 2.0, 1.0 - alpha / 2.0])
    if interval == "basic":
        lower = 2.0 * observed - float(upper_quantile)
        upper = 2.0 * observed - float(lower_quantile)
    else:
        lower = float(lower_quantile)
        upper = float(upper_quantile)
    standard_error = float(distribution.std(ddof=1))

    findings: list[Finding] = []
    warnings: list[str] = []
    if method == "iid":
        findings.append(
            Finding(
                code="BOOTSTRAP_IID_ASSUMPTION",
                title="IID bootstrap assumes independent observations",
                message=(
                    "Use a dependence-aware bootstrap when returns or IC values are "
                    "serially dependent."
                ),
                state=FindingState.WARN,
                severity=Severity.MEDIUM,
                category="statistical_validity",
            )
        )
    else:
        warnings.append(
            "Block-length sensitivity should be checked; one block choice does not prove coverage."
        )
    warnings.append("Effective sample size is not estimated by the v0.1 bootstrap implementation.")

    tables: dict[str, JsonValue] = {
        "distribution_summary": frame_records(_distribution_summary(distribution))
    }
    if store_distribution:
        tables["resample_distribution"] = frame_records(
            pl.DataFrame(
                {
                    "replicate": np.arange(resamples, dtype=np.int64),
                    "statistic": distribution,
                }
            )
        )
    return AnalysisResult(
        metadata=ResultMetadata(
            method=f"validation.bootstrap.{method}",
            method_version=1,
            parameters={
                "statistic": statistic_name,
                "method": method,
                "block_length": resolved_block_length,
                "stationary_restart_probability": (
                    1.0 / resolved_block_length if method == "stationary" else None
                ),
                "resamples": resamples,
                "confidence_level": confidence_level,
                "interval": interval,
                "null_policy": null_policy,
                "backend": backend,
                "rng": "numpy.PCG64/SeedSequence",
                "substream_identity": "(seed, method_version=1, replicate)",
                "batch_size": batch_size,
                "temporary_workspace_bytes": execution_budget.per_batch_workspace_bytes,
                "native_threads": execution_budget.native_threads,
                "input": source,
            },
            seed=resolved_seed,
        ),
        metrics={
            "observed": observed,
            "bootstrap_estimate": float(distribution.mean()),
            "standard_error": standard_error,
            "confidence_lower": lower,
            "confidence_upper": upper,
            "confidence_level": confidence_level,
            "monte_carlo_resolution": 1.0 / (resamples + 1),
            "n_raw": int(values.size),
            "n_effective": None,
            "excluded_rows": excluded,
        },
        findings=tuple(findings),
        tables=tables,
        warnings=tuple(warnings),
    )


def _registry_p_values(
    registry: ExperimentRegistry,
    *,
    metric_name: str,
) -> tuple[pl.DataFrame, dict[str, JsonValue], int]:
    latest = {}
    for attempt in registry.attempts():
        latest[attempt.trial_id] = attempt
    unavailable = [
        attempt
        for attempt in latest.values()
        if attempt.status is not AttemptStatus.COMPLETED
        or attempt.metric_name != metric_name
        or attempt.metric_value is None
    ]
    if unavailable:
        raise DataContractError(
            f"registry has {len(unavailable)} trials without a current completed "
            f"{metric_name!r} metric"
        )
    ordered = sorted(latest.values(), key=lambda attempt: attempt.trial_id)
    frame = pl.DataFrame(
        {
            "trial_id": [attempt.trial_id for attempt in ordered],
            "p_value": [attempt.metric_value for attempt in ordered],
        }
    )
    source: dict[str, JsonValue] = {
        "source_type": "lacuna.experiment.ExperimentRegistry",
        "registry": registry.name,
        "family": registry.family,
        "attempts": len(registry.attempts()),
        "trials": len(ordered),
        "metric_name": metric_name,
    }
    return frame, source, 0


def _p_value_frame(
    data: object,
    *,
    p_value: str,
    trial: str,
    null_policy: Literal["drop", "raise"],
) -> tuple[pl.DataFrame, dict[str, JsonValue], int]:
    if isinstance(data, ExperimentRegistry):
        return _registry_p_values(data, metric_name=p_value)
    if isinstance(data, np.ndarray):
        if data.ndim != 1:
            raise DataContractError("multiple-testing NumPy input must be one-dimensional")
        frame = pl.DataFrame({"trial_id": np.arange(data.size), "p_value": data})
        diagnostics = FrameDiagnostics(
            source_type="numpy.ndarray",
            rows=int(data.size),
            columns=("p_value",),
            lazy_input=False,
            materialized=False,
            adapter_copy="potentially_zero_copy",
            adapter_operations=("numpy_to_polars",),
        )
    elif (
        isinstance(data, Sequence)
        and not isinstance(data, str | bytes)
        and all(isinstance(item, Real) and not isinstance(item, bool) for item in data)
    ):
        frame = pl.DataFrame({"trial_id": range(len(data)), "p_value": data})
        diagnostics = FrameDiagnostics(
            source_type=f"{type(data).__module__}.{type(data).__name__}",
            rows=len(data),
            columns=("p_value",),
            lazy_input=False,
            materialized=False,
            adapter_copy="one_copy",
            adapter_operations=("sequence_to_polars",),
        )
    else:
        frame, diagnostics = eager_frame(data, required=[trial, p_value])
        diagnostics = diagnostics.with_execution("project_trial_and_p_value", "cast_float64")
        require_no_nulls(frame, [trial], name="multiple-testing input")
        require_identifier(frame, trial, name="multiple-testing input")
        require_unique(frame, [trial], name="multiple-testing input")
        require_numeric(frame, [p_value])
        frame = frame.select(
            pl.col(trial).alias("trial_id"), pl.col(p_value).cast(pl.Float64).alias("p_value")
        )
    if frame.is_empty():
        raise DataContractError("multiple testing requires at least one trial")
    frame, excluded = paired_numeric_policy(frame, ["p_value"], null_policy=null_policy)
    if frame.is_empty():
        raise DataContractError("multiple testing has no finite p-values after null handling")
    out_of_range = frame.select(
        ((pl.col("p_value") < 0.0) | (pl.col("p_value") > 1.0)).sum()
    ).item()
    if out_of_range:
        raise DataContractError(f"multiple testing contains {out_of_range} p-values outside [0, 1]")
    return frame, diagnostics.to_parameters(), excluded


def _adjust_p_values(
    values: FloatArray,
    *,
    method: MultipleTestingMethod,
    effective_trials: float | None,
) -> tuple[FloatArray, npt.NDArray[np.int64]]:
    count = values.size
    order = np.argsort(values, kind="stable")
    ordered = values[order]
    if method == "bonferroni":
        factor = effective_trials if effective_trials is not None else float(count)
        adjusted_ordered = np.minimum(ordered * factor, 1.0)
    elif method == "holm":
        raw = ordered * np.arange(count, 0, -1, dtype=np.float64)
        adjusted_ordered = np.minimum(np.maximum.accumulate(raw), 1.0)
    else:
        factor = float(count)
        if method == "benjamini_yekutieli":
            factor *= math.fsum(1.0 / index for index in range(1, count + 1))
        raw = ordered * factor / np.arange(1, count + 1, dtype=np.float64)
        adjusted_ordered = np.minimum(np.minimum.accumulate(raw[::-1])[::-1], 1.0)
    adjusted = np.empty(count, dtype=np.float64)
    adjusted[order] = adjusted_ordered
    ranks = np.empty(count, dtype=np.int64)
    ranks[order] = np.arange(1, count + 1, dtype=np.int64)
    return adjusted, ranks


def multiple_testing(
    data: object,
    *,
    p_value: str = "p_value",
    trial: str = "trial_id",
    method: MultipleTestingMethod = "holm",
    alpha: float = 0.05,
    effective_trials: float | None = None,
    null_policy: Literal["drop", "raise"] = "raise",
) -> AnalysisResult:
    """Adjust a declared family of p-values while preserving every trial identity.

    Benjamini-Hochberg controls false discovery rate under independence or positive
    dependence. Benjamini-Yekutieli is the conservative dependence-robust variant.
    """

    if method not in {
        "bonferroni",
        "holm",
        "benjamini_hochberg",
        "benjamini_yekutieli",
    }:
        raise MethodContractError(
            "method must be 'bonferroni', 'holm', 'benjamini_hochberg', or 'benjamini_yekutieli'"
        )
    if not 0.0 < alpha < 1.0:
        raise MethodContractError("alpha must be between zero and one")
    frame, source, excluded = _p_value_frame(
        data,
        p_value=p_value,
        trial=trial,
        null_policy=null_policy,
    )
    trial_count = frame.height
    if effective_trials is not None:
        if method != "bonferroni":
            raise MethodContractError("effective_trials is only supported for Bonferroni")
        if not 1.0 <= effective_trials <= trial_count:
            raise MethodContractError("effective_trials must be between 1 and the trial count")
    values: FloatArray = frame.get_column("p_value").to_numpy().astype(np.float64, copy=False)
    adjusted, ranks = _adjust_p_values(
        values,
        method=method,
        effective_trials=effective_trials,
    )
    rejected = adjusted <= alpha
    table = frame.with_columns(
        pl.Series("rank", ranks),
        pl.Series("adjusted_p_value", adjusted),
        pl.Series("rejected", rejected),
    ).select("trial_id", "rank", "p_value", "adjusted_p_value", "rejected")
    rejection_count = int(rejected.sum())
    if rejection_count:
        finding = Finding(
            code="MULTIPLE_TESTING_DISCOVERIES",
            title="Evidence survives multiplicity adjustment",
            message="At least one registered trial remains significant after adjustment.",
            state=FindingState.PASS,
            severity=Severity.INFO,
            category="statistical_validity",
            evidence={
                "method": method,
                "alpha": alpha,
                "rejected_trials": rejection_count,
                "trial_count": trial_count,
            },
        )
    else:
        finding = Finding(
            code="MULTIPLE_TESTING_NO_DISCOVERY",
            title="No evidence survives multiplicity adjustment",
            message="No registered trial remains significant at the declared adjusted threshold.",
            state=FindingState.WARN,
            severity=Severity.MEDIUM,
            category="statistical_validity",
            evidence={"method": method, "alpha": alpha, "trial_count": trial_count},
        )
    warnings = []
    if method == "benjamini_hochberg":
        warnings.append(
            "Benjamini-Hochberg assumes independent or positively dependent valid p-values."
        )
    if effective_trials is not None:
        warnings.append("The effective trial count is user-supplied and not estimated by Lacuna.")
    input_fingerprint = fingerprint(
        {
            "trial_ids": frame.get_column("trial_id"),
            "p_values": values,
        },
        namespace="multiple-testing-input",
    )
    return AnalysisResult(
        metadata=ResultMetadata(
            method=f"validation.multiple_testing.{method}",
            method_version=1,
            parameters={
                "method": method,
                "alpha": alpha,
                "effective_trials": effective_trials,
                "null_policy": null_policy,
                "input": source,
            },
            input_fingerprint=input_fingerprint,
        ),
        metrics={
            "trial_count": trial_count,
            "rejected_count": rejection_count,
            "rejected_fraction": rejection_count / trial_count,
            "alpha": alpha,
            "excluded_rows": excluded,
        },
        findings=(finding,),
        tables={"adjusted_p_values": frame_records(table)},
        warnings=tuple(warnings),
    )


def _normalize_grid(
    grid: Mapping[str, Sequence[JsonValue]],
    *,
    max_evaluations: int,
) -> tuple[tuple[str, ...], tuple[tuple[JsonValue, ...], ...]]:
    if not grid:
        raise MethodContractError("parameter grid must contain at least one parameter")
    if max_evaluations < 1:
        raise MethodContractError("max_evaluations must be positive")
    names = tuple(sorted(grid))
    values: list[tuple[JsonValue, ...]] = []
    count = 1
    for name in names:
        if not name or name.strip() != name:
            raise MethodContractError("grid parameter names must be non-empty trimmed strings")
        candidates = grid[name]
        if isinstance(candidates, str | bytes) or not isinstance(candidates, Sequence):
            raise MethodContractError(f"grid parameter {name!r} must contain an ordered sequence")
        if len(candidates) == 0:
            raise MethodContractError(f"grid parameter {name!r} must contain at least one value")
        normalized = tuple(
            cast(JsonValue, json.loads(canonical_json(candidate))) for candidate in candidates
        )
        identities = [canonical_json(candidate) for candidate in normalized]
        if len(set(identities)) != len(identities):
            raise MethodContractError(f"grid parameter {name!r} contains duplicate values")
        values.append(normalized)
        count *= len(normalized)
        if count > max_evaluations:
            raise MethodContractError(
                f"parameter grid contains {count} points, exceeding max_evaluations="
                f"{max_evaluations}"
            )
    return names, tuple(values)


def _surface_selected_point(
    points: Sequence[_SurfacePoint],
    *,
    direction: ObjectiveDirection,
    selected_parameters: Mapping[str, JsonValue] | None,
) -> _SurfacePoint | None:
    if selected_parameters is not None:
        selected_identity = canonical_json(selected_parameters)
        matches = [
            point for point in points if canonical_json(point.parameters) == selected_identity
        ]
        if not matches:
            raise MethodContractError("selected_parameters does not identify a point in the grid")
        return matches[0]
    successful = [point for point in points if point.objective is not None]
    if not successful:
        return None
    sign = 1.0 if direction == "maximize" else -1.0
    return min(
        successful,
        key=lambda point: (
            -sign * cast(float, point.objective),
            canonical_json(point.parameters),
        ),
    )


def _surface_neighbors(
    points: Sequence[_SurfacePoint],
    selected: _SurfacePoint,
    *,
    radius: int,
) -> list[_SurfacePoint]:
    return [
        point
        for point in points
        if point is not selected
        and 0
        < sum(
            abs(left - right) for left, right in zip(point.indices, selected.indices, strict=True)
        )
        <= radius
    ]


def _plateau_width(
    points: Sequence[_SurfacePoint],
    selected: _SurfacePoint,
    *,
    direction: ObjectiveDirection,
    tolerance: float,
) -> int:
    if selected.objective is None:
        return 0
    scale = max(abs(selected.objective), float(np.finfo(np.float64).eps))
    qualifying = {
        point.indices
        for point in points
        if point.objective is not None
        and (
            selected.objective - point.objective
            if direction == "maximize"
            else point.objective - selected.objective
        )
        <= tolerance * scale
    }
    component = {selected.indices}
    frontier = [selected.indices]
    while frontier:
        current = frontier.pop()
        adjacent = {
            candidate
            for candidate in qualifying.difference(component)
            if sum(abs(left - right) for left, right in zip(candidate, current, strict=True)) == 1
        }
        component.update(adjacent)
        frontier.extend(sorted(adjacent))
    return len(component)


def _point_row(point: _SurfacePoint) -> dict[str, JsonValue]:
    return {
        **point.parameters,
        "point_id": point.point_id,
        "status": point.status,
        "objective": point.objective,
        "error_category": point.error_category,
        "warnings": point.warnings,
        "grid_index": point.indices,
    }


def parameter_surface(
    evaluate: Callable[[Mapping[str, JsonValue]], AnalysisResult],
    *,
    grid: Mapping[str, Sequence[JsonValue]],
    objective: str,
    evaluator_name: str,
    sample_id: str,
    code_id: str,
    evaluator_version: int = 1,
    direction: ObjectiveDirection = "maximize",
    selected_parameters: Mapping[str, JsonValue] | None = None,
    selection_sample_id: str | None = None,
    failure_policy: SurfaceFailurePolicy = "record",
    neighborhood_radius: int = 1,
    isolation_threshold: float = 3.0,
    plateau_tolerance: float = 0.1,
    evidence_threshold: float | None = None,
    max_evaluations: int = 10_000,
    registry: ExperimentRegistry | None = None,
) -> AnalysisResult:
    """Evaluate a complete parameter grid and quantify local optimum stability.

    Adjacency uses Manhattan distance over each parameter's declared ordered grid.
    Failed points remain in the surface and in an optional experiment registry.
    """

    if not callable(evaluate):
        raise MethodContractError("evaluate must be callable")
    for value, name in [
        (objective, "objective"),
        (evaluator_name, "evaluator_name"),
        (sample_id, "sample_id"),
        (code_id, "code_id"),
    ]:
        if not value or value.strip() != value:
            raise MethodContractError(f"{name} must be a non-empty trimmed string")
    if evaluator_version < 1:
        raise MethodContractError("evaluator_version must be positive")
    if direction not in {"maximize", "minimize"}:
        raise MethodContractError("direction must be 'maximize' or 'minimize'")
    if failure_policy not in {"record", "raise"}:
        raise MethodContractError("failure_policy must be 'record' or 'raise'")
    if neighborhood_radius < 1:
        raise MethodContractError("neighborhood_radius must be positive")
    if not math.isfinite(isolation_threshold) or isolation_threshold <= 0.0:
        raise MethodContractError("isolation_threshold must be positive and finite")
    if not math.isfinite(plateau_tolerance) or plateau_tolerance < 0.0:
        raise MethodContractError("plateau_tolerance must be non-negative and finite")
    if evidence_threshold is not None and not math.isfinite(evidence_threshold):
        raise MethodContractError("evidence_threshold must be finite when provided")

    parameter_names, grid_values = _normalize_grid(grid, max_evaluations=max_evaluations)
    points: list[_SurfacePoint] = []
    for indices in product(*(range(len(values)) for values in grid_values)):
        parameters = {
            name: grid_values[position][index]
            for position, (name, index) in enumerate(zip(parameter_names, indices, strict=True))
        }
        point_id = fingerprint(parameters, namespace="parameter-surface-point")
        try:
            result = evaluate(parameters)
            if not isinstance(result, AnalysisResult):
                raise DataContractError("evaluate must return an AnalysisResult")
            observed = result.metrics.get(objective)
            if not isinstance(observed, Real) or isinstance(observed, bool):
                raise DataContractError(
                    f"objective metric {objective!r} must be a finite numeric scalar"
                )
            objective_value = float(observed)
            if not math.isfinite(objective_value):
                raise DataContractError(
                    f"objective metric {objective!r} must be a finite numeric scalar"
                )
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as error:
            if failure_policy == "raise":
                raise
            error_category = type(error).__name__
            point = _SurfacePoint(
                indices=tuple(indices),
                parameters=parameters,
                point_id=point_id,
                status="failed",
                objective=None,
                error_category=error_category,
                warnings=(),
            )
            points.append(point)
            if registry is not None:
                registry.record(
                    parameters=parameters,
                    status=AttemptStatus.FAILED,
                    error_category=error_category,
                    method=evaluator_name,
                    method_version=evaluator_version,
                    data_fingerprint=sample_id,
                    code_fingerprint=code_id,
                    metadata={"surface_point_id": point_id},
                )
            continue
        point = _SurfacePoint(
            indices=tuple(indices),
            parameters=parameters,
            point_id=point_id,
            status="completed",
            objective=objective_value,
            error_category=None,
            warnings=result.warnings,
        )
        points.append(point)
        if registry is not None:
            registry.record(
                parameters=parameters,
                metric=objective_value,
                metric_name=objective,
                method=evaluator_name,
                method_version=evaluator_version,
                data_fingerprint=sample_id,
                code_fingerprint=code_id,
                result_fingerprint=result.metadata.input_fingerprint,
                metadata={"surface_point_id": point_id},
            )

    selected = _surface_selected_point(
        points,
        direction=direction,
        selected_parameters=selected_parameters,
    )
    failed_count = sum(point.status == "failed" for point in points)
    findings: list[Finding] = []
    warnings = [
        "Parameter-surface evidence is descriptive unless selection and evaluation samples differ."
    ]
    neighbors: list[_SurfacePoint] = []
    local_median: float | None = None
    local_mad: float | None = None
    isolation_score: float | None = None
    objective_ratio: float | None = None
    plateau_width = 0
    neighbor_failed_fraction: float | None = None
    neighbor_positive_fraction: float | None = None
    neighbor_passing_fraction: float | None = None
    boundary_parameters: tuple[str, ...] = ()

    if selected is None:
        findings.append(
            Finding(
                code="PARAMETER_SURFACE_NO_VALID_POINT",
                title="Parameter surface has no valid point",
                message="Every attempted parameter point failed or had an undefined objective.",
                state=FindingState.FAIL,
                severity=Severity.HIGH,
                category="robustness",
                evidence={"attempted_points": len(points), "failed_points": failed_count},
            )
        )
    elif selected.objective is None:
        findings.append(
            Finding(
                code="PARAMETER_SELECTED_POINT_FAILED",
                title="Selected parameter point failed",
                message="The explicitly selected point did not produce a valid objective.",
                state=FindingState.FAIL,
                severity=Severity.HIGH,
                category="robustness",
                evidence={"selected_parameters": selected.parameters},
            )
        )
    else:
        neighbors = _surface_neighbors(points, selected, radius=neighborhood_radius)
        successful_neighbors = [
            point.objective for point in neighbors if point.objective is not None
        ]
        neighbor_failed_fraction = (
            sum(point.status == "failed" for point in neighbors) / len(neighbors)
            if neighbors
            else None
        )
        if successful_neighbors:
            local_median = float(np.median(successful_neighbors))
            local_mad = float(
                np.median(np.abs(np.asarray(successful_neighbors, dtype=np.float64) - local_median))
            )
            gap = (
                selected.objective - local_median
                if direction == "maximize"
                else local_median - selected.objective
            )
            scale = max(
                local_mad,
                abs(local_median) * 1e-12,
                float(np.finfo(np.float64).eps),
            )
            isolation_score = gap / scale
            if local_median != 0.0 and selected.objective * local_median > 0.0:
                objective_ratio = abs(selected.objective / local_median)
            neighbor_positive_fraction = sum(value > 0.0 for value in successful_neighbors) / len(
                successful_neighbors
            )
            if evidence_threshold is not None:
                neighbor_passing_fraction = sum(
                    (
                        value >= evidence_threshold
                        if direction == "maximize"
                        else value <= evidence_threshold
                    )
                    for value in successful_neighbors
                ) / len(successful_neighbors)
        plateau_width = _plateau_width(
            points,
            selected,
            direction=direction,
            tolerance=plateau_tolerance,
        )
        boundary_parameters = tuple(
            name
            for position, name in enumerate(parameter_names)
            if len(grid_values[position]) > 1
            and selected.indices[position] in {0, len(grid_values[position]) - 1}
        )
        if len(successful_neighbors) < 2:
            isolation_finding = Finding(
                code="PARAMETER_ISOLATION_UNKNOWN",
                title="Parameter isolation cannot be established",
                message="Fewer than two successful neighboring points are available.",
                state=FindingState.UNKNOWN,
                severity=Severity.MEDIUM,
                category="robustness",
                evidence={
                    "successful_neighbors": len(successful_neighbors),
                    "neighbor_count": len(neighbors),
                },
            )
        elif cast(float, isolation_score) >= isolation_threshold and plateau_width == 1:
            isolation_finding = Finding(
                code="PARAMETER_ISOLATED_OPTIMUM",
                title="Selected optimum is locally isolated",
                message="The selected objective materially exceeds its declared neighborhood.",
                state=FindingState.WARN,
                severity=Severity.HIGH,
                category="robustness",
                evidence={
                    "isolation_score": isolation_score,
                    "threshold": isolation_threshold,
                    "local_median": local_median,
                    "local_mad": local_mad,
                    "plateau_width": plateau_width,
                },
            )
        else:
            isolation_finding = Finding(
                code="PARAMETER_LOCAL_STABILITY",
                title="Selected point has local support",
                message="The selected objective is supported by its declared neighborhood.",
                state=FindingState.PASS,
                severity=Severity.INFO,
                category="robustness",
                evidence={
                    "isolation_score": isolation_score,
                    "threshold": isolation_threshold,
                    "plateau_width": plateau_width,
                },
            )
        findings.append(isolation_finding)
        if boundary_parameters:
            findings.append(
                Finding(
                    code="PARAMETER_BOUNDARY_OPTIMUM",
                    title="Selected point lies on a grid boundary",
                    message=(
                        "The declared grid does not bracket the selected point in every dimension."
                    ),
                    state=FindingState.WARN,
                    severity=Severity.MEDIUM,
                    category="robustness",
                    evidence={"boundary_parameters": boundary_parameters},
                )
            )

    if failed_count:
        findings.append(
            Finding(
                code="PARAMETER_SURFACE_FAILURES",
                title="Parameter surface includes failed evaluations",
                message="Failed points remain visible and may weaken neighborhood evidence.",
                state=FindingState.WARN,
                severity=Severity.MEDIUM,
                category="robustness",
                evidence={
                    "failed_points": failed_count,
                    "attempted_points": len(points),
                    "failed_fraction": failed_count / len(points),
                },
            )
        )

    effective_selection_sample = selection_sample_id
    if selected_parameters is None:
        effective_selection_sample = sample_id
    if effective_selection_sample is None:
        findings.append(
            Finding(
                code="PARAMETER_SELECTION_SAMPLE_UNKNOWN",
                title="Selection sample identity is unknown",
                message="Independent selection and evaluation evidence cannot be established.",
                state=FindingState.UNKNOWN,
                severity=Severity.MEDIUM,
                category="research_process",
            )
        )
    elif effective_selection_sample == sample_id:
        findings.append(
            Finding(
                code="PARAMETER_SELECTION_REUSE",
                title="Selection and evaluation reuse the same sample",
                message="The surface is descriptive and is not independent out-of-sample evidence.",
                state=FindingState.WARN,
                severity=Severity.HIGH,
                category="research_process",
                evidence={"sample_id": sample_id},
            )
        )
    else:
        findings.append(
            Finding(
                code="PARAMETER_SELECTION_SEPARATION",
                title="Selection and evaluation samples are distinct",
                message="Recorded sample identities distinguish selection from evaluation.",
                state=FindingState.PASS,
                severity=Severity.INFO,
                category="research_process",
                evidence={
                    "selection_sample_id": effective_selection_sample,
                    "evaluation_sample_id": sample_id,
                },
            )
        )

    surface_rows = tuple(_point_row(point) for point in points)
    neighbor_rows = tuple(_point_row(point) for point in neighbors)
    input_fingerprint = fingerprint(
        {
            "grid": {
                name: values for name, values in zip(parameter_names, grid_values, strict=True)
            },
            "evaluator_name": evaluator_name,
            "evaluator_version": evaluator_version,
            "sample_id": sample_id,
            "code_id": code_id,
        },
        namespace="parameter-surface-input",
    )
    return AnalysisResult(
        metadata=ResultMetadata(
            method="validation.parameter_surface",
            method_version=1,
            parameters={
                "objective": objective,
                "direction": direction,
                "evaluator_name": evaluator_name,
                "evaluator_version": evaluator_version,
                "sample_id": sample_id,
                "selection_sample_id": effective_selection_sample,
                "code_id": code_id,
                "failure_policy": failure_policy,
                "neighborhood": "ordered_grid_manhattan",
                "neighborhood_radius": neighborhood_radius,
                "isolation_threshold": isolation_threshold,
                "plateau_tolerance": plateau_tolerance,
                "evidence_threshold": evidence_threshold,
            },
            input_fingerprint=input_fingerprint,
        ),
        metrics={
            "attempted_points": len(points),
            "successful_points": len(points) - failed_count,
            "failed_points": failed_count,
            "selected_point_id": selected.point_id if selected is not None else None,
            "selected_objective": selected.objective if selected is not None else None,
            "local_median": local_median,
            "local_mad": local_mad,
            "isolation_score": isolation_score,
            "objective_to_local_median_ratio": objective_ratio,
            "plateau_width": plateau_width,
            "neighbor_count": len(neighbors),
            "neighbor_failed_fraction": neighbor_failed_fraction,
            "neighbor_positive_fraction": neighbor_positive_fraction,
            "neighbor_passing_fraction": neighbor_passing_fraction,
            "boundary_parameters": boundary_parameters,
        },
        findings=tuple(findings),
        tables={"parameter_surface": surface_rows, "selected_neighborhood": neighbor_rows},
        warnings=tuple(warnings),
    )


__all__ = [
    "BootstrapMethod",
    "IntervalMethod",
    "MultipleTestingMethod",
    "ObjectiveDirection",
    "PBOStatistic",
    "PBOTieBreak",
    "PermutationAlternative",
    "PermutationScheme",
    "PermutationStatistic",
    "Statistic",
    "SurfaceFailurePolicy",
    "bootstrap",
    "joint_stationary_bootstrap",
    "multiple_testing",
    "parameter_surface",
    "permutation_test",
    "probability_of_backtest_overfitting",
    "reality_check",
    "sharpe_inference",
    "superior_predictive_ability",
]
