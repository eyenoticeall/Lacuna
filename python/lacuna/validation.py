"""Dependence-aware resampling for financial research evidence."""

from __future__ import annotations

import math
import secrets
from collections.abc import Callable, Sequence
from typing import Literal, TypeAlias

import numpy as np
import numpy.typing as npt
import polars as pl

from lacuna._frames import FrameDiagnostics, eager_frame, frame_records, paired_numeric_policy
from lacuna.config import get_config
from lacuna.exceptions import DataContractError, MethodContractError
from lacuna.types import AnalysisResult, Finding, FindingState, JsonValue, ResultMetadata, Severity

FloatArray: TypeAlias = npt.NDArray[np.float64]
BootstrapMethod: TypeAlias = Literal["iid", "moving", "circular", "stationary"]
IntervalMethod: TypeAlias = Literal["percentile", "basic"]
Statistic: TypeAlias = Literal["mean", "median", "sharpe"] | Callable[[FloatArray], float]


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
    values: FloatArray,
    indices: Sequence[npt.NDArray[np.intp]],
) -> list[float] | None:
    try:
        from lacuna import _native
    except ImportError:
        return None
    if not hasattr(_native, "bootstrap_means"):
        return None
    flattened = np.concatenate(indices).astype(np.uintp, copy=False)
    offsets = np.arange(0, flattened.size + 1, values.size, dtype=np.uintp)
    return _native.bootstrap_means(values.tolist(), flattened.tolist(), offsets.tolist())


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

    resolved_seed = seed if seed is not None else get_config().seed
    if resolved_seed is None:
        resolved_seed = secrets.randbits(63)
    if resolved_seed < 0:
        raise MethodContractError("seed must be non-negative")

    observed = statistic_function(values)
    if not math.isfinite(observed):
        raise DataContractError("observed statistic is not finite")
    distribution: FloatArray = np.empty(resamples, dtype=np.float64)
    bytes_per_resample = max(values.size * np.dtype(np.intp).itemsize, 1)
    batch_size = max(1, min(resamples, batch_memory_bytes // bytes_per_resample))
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
        native_means = (
            _native_mean_batch(values, index_batch)
            if statistic_name == "mean" and use_native
            else None
        )
        if native_means is not None:
            distribution[batch_start:batch_end] = native_means
            backend = "rust_native"
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


__all__ = ["BootstrapMethod", "IntervalMethod", "Statistic", "bootstrap"]
