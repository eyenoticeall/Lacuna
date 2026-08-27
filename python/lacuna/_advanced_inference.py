"""Validated reference implementations for advanced financial inference."""

from __future__ import annotations

import math
import secrets
import time
from collections.abc import Callable, Sequence
from itertools import combinations
from statistics import NormalDist
from typing import Literal, TypeAlias

import numpy as np
import numpy.typing as npt
import polars as pl

from lacuna._execution import ResolvedExecutionBudget, resolve_execution_budget
from lacuna._frames import (
    FrameDiagnostics,
    eager_frame,
    frame_records,
    paired_numeric_policy,
    require_identifier,
    require_no_nulls,
    require_numeric,
    require_time_key,
)
from lacuna._native_arrays import readonly_float64_matrix, readonly_int64_matrix
from lacuna.config import get_config
from lacuna.exceptions import DataContractError, MethodContractError
from lacuna.experiment import fingerprint
from lacuna.types import AnalysisResult, Finding, FindingState, JsonValue, ResultMetadata, Severity

FloatArray: TypeAlias = npt.NDArray[np.float64]
PermutationScheme: TypeAlias = Literal[
    "unrestricted", "within_date", "within_group", "block", "sign_flip"
]
PermutationAlternative: TypeAlias = Literal["two_sided", "greater", "less"]
PermutationStatistic: TypeAlias = (
    Literal["mean", "pearson"] | Callable[[FloatArray, FloatArray | None], float]
)
PBOStatistic: TypeAlias = Literal["mean", "sharpe"]
PBOTieBreak: TypeAlias = Literal["raise", "first"]
_PBOBackend: TypeAlias = Literal["auto", "reference", "native"]
_PBO_NATIVE_CROSSOVER_COMBINATIONS = 512


def _resolved_seed(seed: int | None) -> int:
    resolved = seed if seed is not None else get_config().seed
    if resolved is None:
        resolved = secrets.randbits(63)
    if resolved < 0:
        raise MethodContractError("seed must be non-negative")
    return resolved


def _replicate_rng(seed: int, method_version: int, replicate: int) -> np.random.Generator:
    return np.random.default_rng(np.random.SeedSequence([seed, method_version, replicate]))


def _distribution_summary(distribution: FloatArray) -> tuple[JsonValue, ...]:
    probabilities = np.asarray([0.0, 0.01, 0.025, 0.05, 0.25, 0.5, 0.75, 0.95, 0.975, 0.99, 1.0])
    return frame_records(
        pl.DataFrame(
            {
                "probability": probabilities,
                "value": np.quantile(distribution, probabilities),
            }
        )
    )


def _permutation_input(
    data: object,
    *,
    value: str,
    paired_with: str | None,
    stratum: str | None,
    stratum_kind: Literal["time", "group"] | None,
    null_policy: Literal["drop", "raise"],
) -> tuple[FloatArray, FloatArray | None, np.ndarray | None, dict[str, JsonValue], int]:
    numeric_columns = [value, *([paired_with] if paired_with is not None else [])]
    required = [*numeric_columns, *([stratum] if stratum is not None else [])]
    if isinstance(data, np.ndarray):
        if stratum is not None:
            raise DataContractError("stratified permutation requires named tabular input")
        if data.ndim == 1 and paired_with is None:
            frame = pl.DataFrame({value: data})
        elif data.ndim == 2 and data.shape[1] == 2 and paired_with is not None:
            frame = pl.DataFrame({value: data[:, 0], paired_with: data[:, 1]})
        else:
            raise DataContractError(
                "permutation NumPy input must be one-dimensional, or have exactly two columns "
                "when paired_with is supplied"
            )
        diagnostics = FrameDiagnostics(
            source_type="numpy.ndarray",
            rows=int(data.shape[0]),
            columns=tuple(numeric_columns),
            lazy_input=False,
            materialized=False,
            adapter_copy="potentially_zero_copy",
            adapter_operations=("numpy_to_polars",),
        )
    elif (
        isinstance(data, Sequence)
        and not isinstance(data, str | bytes)
        and paired_with is None
        and stratum is None
    ):
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
        frame, diagnostics = eager_frame(data, required=required)
    if stratum is not None:
        require_no_nulls(frame, [stratum], name="permutation input")
        if stratum_kind == "time":
            require_time_key(frame, stratum, name="permutation input")
        else:
            require_identifier(frame, stratum, name="permutation input")
    require_numeric(frame, numeric_columns)
    projected = frame.select(
        *[pl.col(column).cast(pl.Float64).alias(column) for column in numeric_columns],
        *([pl.col(stratum)] if stratum is not None else []),
    )
    projected, excluded = paired_numeric_policy(
        projected,
        numeric_columns,
        null_policy=null_policy,
    )
    if projected.height < 3:
        raise DataContractError("permutation inference requires at least three finite observations")
    values: FloatArray = projected.get_column(value).to_numpy().astype(np.float64, copy=False)
    paired: FloatArray | None = (
        projected.get_column(paired_with).to_numpy().astype(np.float64, copy=False)
        if paired_with is not None
        else None
    )
    strata = projected.get_column(stratum).to_numpy() if stratum is not None else None
    return values, paired, strata, diagnostics.to_parameters(), excluded


def _permutation_statistic(
    statistic: PermutationStatistic,
) -> tuple[str, Callable[[FloatArray, FloatArray | None], float]]:
    if callable(statistic):
        name = getattr(statistic, "__name__", "custom")

        def custom(values: FloatArray, paired: FloatArray | None) -> float:
            return float(statistic(values, paired))

        return name, custom
    if statistic == "mean":
        return "mean", lambda values, paired: float(values.mean())
    if statistic == "pearson":

        def pearson(values: FloatArray, paired: FloatArray | None) -> float:
            if paired is None:
                raise MethodContractError("Pearson permutation requires paired_with")
            left = values - values.mean()
            right = paired - paired.mean()
            left_sum_squares = float(np.dot(left, left))
            right_sum_squares = float(np.dot(right, right))
            if left_sum_squares == 0.0 or right_sum_squares == 0.0:
                raise DataContractError("Pearson statistic is undefined for a constant input")
            return float(np.dot(left, right) / math.sqrt(left_sum_squares * right_sum_squares))

        return "pearson", pearson
    raise MethodContractError("statistic must be 'mean', 'pearson', or a callable")


def _permuted_values(
    values: FloatArray,
    *,
    scheme: PermutationScheme,
    strata: np.ndarray | None,
    block_length: int | None,
    rng: np.random.Generator,
) -> FloatArray:
    if scheme == "sign_flip":
        signs = rng.choice(np.asarray([-1.0, 1.0]), size=values.size)
        return values * signs
    if scheme == "unrestricted":
        return values[rng.permutation(values.size)]
    if scheme in {"within_date", "within_group"}:
        assert strata is not None
        result = values.copy()
        for label in dict.fromkeys(strata.tolist()):
            indices = np.flatnonzero(strata == label)
            result[indices] = values[indices[rng.permutation(indices.size)]]
        return result
    assert scheme == "block"
    assert block_length is not None
    blocks = [
        np.arange(start, min(start + block_length, values.size))
        for start in range(0, values.size, block_length)
    ]
    order = rng.permutation(len(blocks))
    indices = np.concatenate([blocks[index] for index in order])
    return values[indices]


def permutation_test(
    data: object,
    *,
    value: str = "value",
    paired_with: str | None = None,
    statistic: PermutationStatistic = "mean",
    scheme: PermutationScheme = "sign_flip",
    time: str = "time",
    group: str = "group",
    block_length: int | None = None,
    permutations: int = 1_000,
    alternative: PermutationAlternative = "two_sided",
    seed: int | None = None,
    null_policy: Literal["drop", "raise"] = "raise",
    store_distribution: bool = False,
) -> AnalysisResult:
    """Test a statistic under an explicit exchangeability transformation.

    ``sign_flip`` tests a zero-centered one-sample null. Other schemes
    permute ``value`` relative to ``paired_with`` and therefore require the
    paired column. Date/group schemes permute only within the named strata;
    block permutation reorders non-overlapping chronological blocks.
    """

    if scheme not in {"unrestricted", "within_date", "within_group", "block", "sign_flip"}:
        raise MethodContractError(
            "scheme must be 'unrestricted', 'within_date', 'within_group', 'block', or 'sign_flip'"
        )
    if alternative not in {"two_sided", "greater", "less"}:
        raise MethodContractError("alternative must be 'two_sided', 'greater', or 'less'")
    if isinstance(permutations, bool) or not isinstance(permutations, int):
        raise MethodContractError("permutations must be an integer")
    if permutations < 100:
        raise MethodContractError("permutations must be at least 100 for inferential output")
    if scheme != "sign_flip" and paired_with is None:
        raise MethodContractError(f"{scheme} permutation requires paired_with")
    if scheme != "sign_flip" and statistic == "mean":
        raise MethodContractError(
            "the built-in mean is invariant to reordering; use sign_flip or a "
            "paired/order-sensitive statistic"
        )
    stratum = time if scheme == "within_date" else group if scheme == "within_group" else None
    stratum_kind: Literal["time", "group"] | None = (
        "time" if scheme == "within_date" else "group" if scheme == "within_group" else None
    )
    values, paired, strata, source, excluded = _permutation_input(
        data,
        value=value,
        paired_with=paired_with,
        stratum=stratum,
        stratum_kind=stratum_kind,
        null_policy=null_policy,
    )
    if scheme == "block":
        if block_length is None:
            raise MethodContractError("block permutation requires block_length")
        if not 1 <= block_length < values.size:
            raise MethodContractError("block_length must be between 1 and sample size - 1")
        if math.ceil(values.size / block_length) < 2:
            raise MethodContractError("block permutation requires at least two blocks")
    elif block_length is not None:
        raise MethodContractError("block_length is only valid for block permutation")
    if strata is not None:
        counts = pl.Series(strata).value_counts().get_column("count")
        if int((counts >= 2).sum()) == 0:
            raise DataContractError(
                "stratified permutation requires a stratum with two observations"
            )

    statistic_name, statistic_function = _permutation_statistic(statistic)
    observed = statistic_function(values, paired)
    if not math.isfinite(observed):
        raise DataContractError("observed permutation statistic is not finite")
    resolved_seed = _resolved_seed(seed)
    distribution: FloatArray = np.empty(permutations, dtype=np.float64)
    paired_centered: FloatArray | None = None
    paired_sum_squares: float | None = None
    invariant_value_sum_squares: float | None = None
    if statistic_name == "pearson":
        assert paired is not None
        paired_centered = paired - paired.mean()
        paired_sum_squares = float(np.dot(paired_centered, paired_centered))
        if scheme != "sign_flip":
            centered_values = values - values.mean()
            invariant_value_sum_squares = float(np.dot(centered_values, centered_values))
    for replicate in range(permutations):
        rng = _replicate_rng(resolved_seed, 2, replicate)
        permuted = _permuted_values(
            values,
            scheme=scheme,
            strata=strata,
            block_length=block_length,
            rng=rng,
        )
        if paired_centered is not None and paired_sum_squares is not None:
            if invariant_value_sum_squares is None:
                centered_permuted = permuted - permuted.mean()
                value_sum_squares = float(np.dot(centered_permuted, centered_permuted))
                numerator = float(np.dot(centered_permuted, paired_centered))
            else:
                value_sum_squares = invariant_value_sum_squares
                numerator = float(np.dot(permuted, paired_centered))
            denominator = math.sqrt(value_sum_squares * paired_sum_squares)
            if denominator == 0.0:
                raise DataContractError("Pearson statistic is undefined for a constant input")
            distribution[replicate] = numerator / denominator
        else:
            distribution[replicate] = statistic_function(permuted, paired)
    if not np.isfinite(distribution).all():
        raise DataContractError(
            "one or more permutation replicates produced a non-finite statistic"
        )
    if alternative == "greater":
        exceedances = int(np.count_nonzero(distribution >= observed))
    elif alternative == "less":
        exceedances = int(np.count_nonzero(distribution <= observed))
    else:
        exceedances = int(np.count_nonzero(np.abs(distribution) >= abs(observed)))
    p_value = (exceedances + 1.0) / (permutations + 1.0)
    tables: dict[str, JsonValue] = {"distribution_summary": _distribution_summary(distribution)}
    if store_distribution:
        tables["permutation_distribution"] = frame_records(
            pl.DataFrame(
                {
                    "replicate": np.arange(permutations, dtype=np.int64),
                    "statistic": distribution,
                }
            )
        )
    return AnalysisResult(
        metadata=ResultMetadata(
            method=f"validation.permutation.{scheme}",
            method_version=2,
            parameters={
                "value_column": value,
                "paired_column": paired_with,
                "statistic": statistic_name,
                "scheme": scheme,
                "stratum_column": stratum,
                "block_length": block_length,
                "permutations": permutations,
                "alternative": alternative,
                "null_policy": null_policy,
                "rng": "numpy.PCG64/SeedSequence",
                "substream_identity": "(seed, method_version=2, replicate)",
                "backend": (
                    "numpy_pearson_reducer"
                    if statistic_name == "pearson"
                    else "python_callable"
                    if callable(statistic)
                    else "numpy_reference"
                ),
                "input": source,
            },
            seed=resolved_seed,
            input_fingerprint=fingerprint(
                {
                    "values": values,
                    "paired": paired,
                },
                namespace="permutation-input",
            ),
        ),
        metrics={
            "observed": observed,
            "p_value": p_value,
            "exceedances": exceedances,
            "monte_carlo_resolution": 1.0 / (permutations + 1.0),
            "n_raw": int(values.size + excluded),
            "n_effective": int(values.size),
            "excluded_rows": excluded,
        },
        tables=tables,
        warnings=(
            "The p-value is valid only when the selected transformation is exchangeable "
            "under the null.",
        ),
    )


def _sample_moments(values: FloatArray) -> tuple[float, float, float, float]:
    standard_deviation = float(values.std(ddof=1))
    if standard_deviation == 0.0:
        raise DataContractError("Sharpe inference is undefined for zero-variance returns")
    mean = float(values.mean())
    centered = values - mean
    population_scale = float(np.sqrt(np.mean(centered**2)))
    skewness = float(np.mean(centered**3) / population_scale**3)
    kurtosis = float(np.mean(centered**4) / population_scale**4)
    return mean, standard_deviation, skewness, kurtosis


def sharpe_inference(
    data: object,
    *,
    value: str = "value",
    benchmark: float = 0.0,
    confidence_level: float = 0.95,
    annualization: float = 1.0,
    trial_sharpes: Sequence[float] | None = None,
    independent_trials: float | None = None,
    null_policy: Literal["drop", "raise"] = "raise",
) -> AnalysisResult:
    """Compute Sharpe uncertainty, PSR, DSR, and minimum track-record length.

    Sharpe values are reported at ``annualization`` scale. Skewness and
    Pearson kurtosis are empirical standardized central moments. The
    asymptotic standard error follows Bailey and López de Prado's
    non-Normal-return formulation.
    """

    if isinstance(benchmark, bool) or not math.isfinite(benchmark):
        raise MethodContractError("benchmark must be finite")
    if not 0.5 < confidence_level < 1.0:
        raise MethodContractError("confidence_level must be between 0.5 and 1")
    if isinstance(annualization, bool) or not math.isfinite(annualization) or annualization <= 0.0:
        raise MethodContractError("annualization must be positive and finite")
    values, source, excluded = _one_dimensional_values(
        data,
        value=value,
        null_policy=null_policy,
        name="Sharpe inference",
        minimum=3,
    )
    mean, standard_deviation, skewness, kurtosis = _sample_moments(values)
    scale = math.sqrt(annualization)
    periodic_sharpe = mean / standard_deviation
    observed_sharpe = periodic_sharpe * scale
    benchmark_periodic = benchmark / scale
    variance_factor = (
        1.0 - skewness * periodic_sharpe + ((kurtosis - 1.0) / 4.0) * periodic_sharpe**2
    )
    if not math.isfinite(variance_factor) or variance_factor <= 0.0:
        raise DataContractError("estimated Sharpe variance is not positive")
    periodic_standard_error = math.sqrt(variance_factor / (values.size - 1))
    standard_error = periodic_standard_error * scale
    z_score = (periodic_sharpe - benchmark_periodic) / periodic_standard_error
    psr = NormalDist().cdf(z_score)
    critical_z = NormalDist().inv_cdf(confidence_level)
    interval_z = NormalDist().inv_cdf(0.5 + confidence_level / 2.0)
    minimum_track_record: float | None = None
    if periodic_sharpe > benchmark_periodic:
        minimum_track_record = (
            1.0 + variance_factor * (critical_z / (periodic_sharpe - benchmark_periodic)) ** 2
        )

    trial_rows: tuple[JsonValue, ...] = ()
    deflated_sharpe_ratio: float | None = None
    deflated_threshold: float | None = None
    trial_count: int | None = None
    effective_trials: float | None = None
    trial_sharpe_mean: float | None = None
    trial_sharpe_standard_deviation: float | None = None
    warnings = [
        "PSR/DSR use an asymptotic Sharpe distribution; short samples and unstable "
        "fourth moments require caution."
    ]
    if trial_sharpes is not None:
        try:
            trials: FloatArray = np.asarray(trial_sharpes, dtype=np.float64)
        except (TypeError, ValueError) as error:
            raise DataContractError("trial_sharpes must contain numeric values") from error
        if trials.ndim != 1 or trials.size < 2 or not np.isfinite(trials).all():
            raise DataContractError("trial_sharpes must contain at least two finite values")
        if not bool(np.isclose(trials, observed_sharpe, rtol=1e-10, atol=1e-12).any()):
            raise DataContractError(
                "trial_sharpes must include the selected strategy's observed Sharpe ratio"
            )
        trial_count = int(trials.size)
        effective_trials = float(trial_count) if independent_trials is None else independent_trials
        if (
            isinstance(effective_trials, bool)
            or not math.isfinite(effective_trials)
            or effective_trials < 1.0
            or effective_trials > trial_count
        ):
            raise MethodContractError(
                "independent_trials must be finite and between 1 and the trial count"
            )
        periodic_trials = trials / scale
        trial_mean = float(periodic_trials.mean())
        trial_standard_deviation = float(periodic_trials.std(ddof=1))
        trial_sharpe_mean = trial_mean * scale
        trial_sharpe_standard_deviation = trial_standard_deviation * scale
        if effective_trials == 1.0 or trial_standard_deviation == 0.0:
            expected_maximum = trial_mean
        else:
            gamma = 0.5772156649015329
            normal = NormalDist()
            expected_maximum = trial_mean + trial_standard_deviation * (
                (1.0 - gamma) * normal.inv_cdf(1.0 - 1.0 / effective_trials)
                + gamma * normal.inv_cdf(1.0 - 1.0 / (effective_trials * math.e))
            )
        deflated_threshold = expected_maximum * scale
        deflated_z = (periodic_sharpe - expected_maximum) / periodic_standard_error
        deflated_sharpe_ratio = NormalDist().cdf(deflated_z)
        trial_rows = frame_records(
            pl.DataFrame(
                {
                    "trial": np.arange(trial_count, dtype=np.int64),
                    "sharpe": trials,
                }
            )
        )
        if independent_trials is None:
            warnings.append(
                "DSR treats all supplied trials as independent; pass independent_trials "
                "when a defensible effective count is available."
            )
    elif independent_trials is not None:
        raise MethodContractError("independent_trials requires the complete trial_sharpes family")

    lower = observed_sharpe - interval_z * standard_error
    upper = observed_sharpe + interval_z * standard_error
    findings = (
        Finding(
            code="SHARPE_EXCEEDS_BENCHMARK" if psr >= confidence_level else "SHARPE_UNCERTAIN",
            title=(
                "Sharpe evidence exceeds the declared benchmark"
                if psr >= confidence_level
                else "Sharpe evidence is not conclusive"
            ),
            message=(
                "The probabilistic Sharpe ratio reaches the declared confidence level."
                if psr >= confidence_level
                else "The probabilistic Sharpe ratio does not reach the declared confidence level."
            ),
            state=FindingState.PASS if psr >= confidence_level else FindingState.WARN,
            severity=Severity.INFO if psr >= confidence_level else Severity.MEDIUM,
            category="statistical_validity",
            evidence={"psr": psr, "confidence_level": confidence_level},
        ),
    )
    return AnalysisResult(
        metadata=ResultMetadata(
            method="validation.sharpe_inference",
            method_version=1,
            parameters={
                "value_column": value,
                "benchmark": benchmark,
                "confidence_level": confidence_level,
                "confidence_interval": "two-sided asymptotic normal",
                "minimum_track_record_confidence": "one-sided",
                "annualization": annualization,
                "kurtosis_convention": "Pearson (normal=3)",
                "moment_estimator": "empirical standardized central moments",
                "independent_trials": effective_trials,
                "null_policy": null_policy,
                "input": source,
            },
            input_fingerprint=fingerprint(values, namespace="sharpe-inference-input"),
        ),
        metrics={
            "observed_sharpe": observed_sharpe,
            "standard_error": standard_error,
            "confidence_lower": lower,
            "confidence_upper": upper,
            "probabilistic_sharpe_ratio": psr,
            "minimum_track_record_observations": minimum_track_record,
            "deflated_sharpe_ratio": deflated_sharpe_ratio,
            "deflated_sharpe_threshold": deflated_threshold,
            "trial_count": trial_count,
            "trial_sharpe_mean": trial_sharpe_mean,
            "trial_sharpe_standard_deviation": trial_sharpe_standard_deviation,
            "n_raw": int(values.size + excluded),
            "n_effective": int(values.size),
            "excluded_rows": excluded,
            "mean": mean,
            "standard_deviation": standard_deviation,
            "skewness": skewness,
            "kurtosis": kurtosis,
        },
        findings=findings,
        tables={"trial_sharpes": trial_rows},
        warnings=tuple(warnings),
    )


def _one_dimensional_values(
    data: object,
    *,
    value: str,
    null_policy: Literal["drop", "raise"],
    name: str,
    minimum: int,
) -> tuple[FloatArray, dict[str, JsonValue], int]:
    if isinstance(data, np.ndarray):
        if data.ndim != 1:
            raise DataContractError(f"{name} NumPy input must be one-dimensional")
        frame = pl.DataFrame({value: data})
        diagnostics = FrameDiagnostics(
            source_type="numpy.ndarray",
            rows=int(data.size),
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
    frame = frame.select(pl.col(value).cast(pl.Float64).alias(value))
    frame, excluded = paired_numeric_policy(frame, [value], null_policy=null_policy)
    if frame.height < minimum:
        raise DataContractError(f"{name} requires at least {minimum} finite observations")
    values: FloatArray = frame.get_column(value).to_numpy().astype(np.float64, copy=False)
    return values, diagnostics.to_parameters(), excluded


def _strategy_matrix(
    data: object,
    *,
    strategy_columns: Sequence[str] | None,
    name: str,
) -> tuple[FloatArray, tuple[str, ...], dict[str, JsonValue]]:
    matrix: FloatArray
    if isinstance(data, np.ndarray):
        if data.ndim != 2:
            raise DataContractError(f"{name} NumPy input must be two-dimensional")
        matrix = np.asarray(data, dtype=np.float64)
        names = tuple(f"strategy_{index}" for index in range(matrix.shape[1]))
        source: dict[str, JsonValue] = {
            "source_type": "numpy.ndarray",
            "rows": int(matrix.shape[0]),
            "columns": names,
            "adapter_copy": "potentially_zero_copy",
        }
    else:
        frame, diagnostics = eager_frame(data)
        if strategy_columns is None:
            names = tuple(column for column, dtype in frame.schema.items() if dtype.is_numeric())
        else:
            names = tuple(strategy_columns)
        if not names:
            raise DataContractError(f"{name} requires at least two numeric strategy columns")
        if len(set(names)) != len(names):
            raise DataContractError(f"{name} strategy columns must be unique")
        missing = [column for column in names if column not in frame.columns]
        if missing:
            raise DataContractError(f"{name} is missing strategy columns: {', '.join(missing)}")
        require_numeric(frame, names)
        selected = frame.select(*[pl.col(column).cast(pl.Float64) for column in names])
        selected, excluded = paired_numeric_policy(selected, names, null_policy="raise")
        assert excluded == 0
        matrix = selected.to_numpy().astype(np.float64, copy=False)
        source = diagnostics.to_parameters()
    if matrix.shape[0] < 4:
        raise DataContractError(f"{name} requires at least four synchronous observations")
    if matrix.shape[1] < 2:
        raise DataContractError(f"{name} requires at least two strategy columns")
    if not np.isfinite(matrix).all():
        raise DataContractError(f"{name} must contain only finite values")
    return matrix, names, source


def _performance(matrix: FloatArray, statistic: PBOStatistic) -> FloatArray:
    if statistic == "mean":
        return matrix.mean(axis=0)
    standard_deviations = matrix.std(axis=0, ddof=1)
    if np.any(standard_deviations == 0.0):
        raise DataContractError("PBO Sharpe statistic is undefined for a constant strategy")
    return matrix.mean(axis=0) / standard_deviations


def _average_ranks(values: FloatArray) -> FloatArray:
    order = np.argsort(values, kind="stable")
    ranks = np.empty(values.size, dtype=np.float64)
    position = 0
    while position < values.size:
        end = position + 1
        while end < values.size and values[order[end]] == values[order[position]]:
            end += 1
        ranks[order[position:end]] = (position + 1 + end) / 2.0
        position = end
    return ranks


def _reference_pbo_for_partitions(
    matrix: FloatArray,
    names: tuple[str, ...],
    *,
    partitions: int,
    statistic: PBOStatistic,
    tie_break: PBOTieBreak,
    max_combinations: int,
) -> tuple[float, list[dict[str, JsonValue]], int]:
    if isinstance(partitions, bool) or not isinstance(partitions, int):
        raise MethodContractError("PBO partitions must be an integer")
    if partitions < 2 or partitions % 2:
        raise MethodContractError("PBO partitions must be an even integer of at least 2")
    if matrix.shape[0] % partitions:
        raise DataContractError("PBO requires equal partitions; row count must divide partitions")
    combination_count = math.comb(partitions, partitions // 2)
    if combination_count > max_combinations:
        raise MethodContractError(
            "PBO combination count exceeds max_combinations; reduce partitions or raise the "
            "explicit safety limit"
        )
    group_size = matrix.shape[0] // partitions
    groups = tuple(
        np.arange(group * group_size, (group + 1) * group_size, dtype=np.intp)
        for group in range(partitions)
    )
    rows: list[dict[str, JsonValue]] = []
    tie_count = 0
    all_groups = set(range(partitions))
    for combination_index, in_sample_groups in enumerate(
        combinations(range(partitions), partitions // 2)
    ):
        out_of_sample_groups = tuple(sorted(all_groups.difference(in_sample_groups)))
        in_sample_indices = np.concatenate([groups[group] for group in in_sample_groups])
        out_of_sample_indices = np.concatenate([groups[group] for group in out_of_sample_groups])
        in_sample_performance = _performance(matrix[in_sample_indices], statistic)
        out_of_sample_performance = _performance(matrix[out_of_sample_indices], statistic)
        best = np.flatnonzero(in_sample_performance == in_sample_performance.max())
        if best.size > 1:
            tie_count += 1
            if tie_break == "raise":
                raise DataContractError(
                    "PBO in-sample selection has a tie; use tie_break='first' only when the "
                    "declared strategy order is a defensible deterministic rule"
                )
        selected = int(best[0])
        rank = float(_average_ranks(out_of_sample_performance)[selected])
        relative_rank = rank / (matrix.shape[1] + 1.0)
        logit = math.log(relative_rank / (1.0 - relative_rank))
        rows.append(
            {
                "combination": combination_index,
                "in_sample_groups": tuple(in_sample_groups),
                "out_of_sample_groups": out_of_sample_groups,
                "selected_strategy": names[selected],
                "selected_strategy_index": selected,
                "in_sample_performance": float(in_sample_performance[selected]),
                "out_of_sample_performance": float(out_of_sample_performance[selected]),
                "out_of_sample_rank": rank,
                "relative_rank": relative_rank,
                "logit": logit,
                "underperformed_median": logit <= 0.0,
            }
        )
    pbo = sum(bool(row["underperformed_median"]) for row in rows) / len(rows)
    return pbo, rows, tie_count


def _combined_partition_performance(
    partition_means: FloatArray,
    partition_m2: FloatArray,
    groups: tuple[int, ...],
    *,
    group_size: int,
    statistic: PBOStatistic,
) -> FloatArray:
    """Combine stable per-partition moments without reconstructing selected rows."""

    mean = np.zeros(partition_means.shape[1], dtype=np.float64)
    m2 = np.zeros(partition_means.shape[1], dtype=np.float64)
    count = 0
    for group in groups:
        next_count = count + group_size
        delta = partition_means[group] - mean
        mean = mean + delta * (group_size / next_count)
        if count:
            m2 = m2 + partition_m2[group] + delta * delta * (count * group_size / next_count)
        else:
            m2 = partition_m2[group].copy()
        count = next_count
    if statistic == "mean":
        return mean
    variance = m2 / (count - 1)
    if np.any(variance <= 0.0) or not np.isfinite(variance).all():
        raise DataContractError("PBO Sharpe statistic is undefined for a constant strategy")
    return mean / np.sqrt(variance)


def _pbo_for_partitions_reference(
    matrix: FloatArray,
    names: tuple[str, ...],
    *,
    partitions: int,
    statistic: PBOStatistic,
    tie_break: PBOTieBreak,
    max_combinations: int,
) -> tuple[float, list[dict[str, JsonValue]], int]:
    if isinstance(partitions, bool) or not isinstance(partitions, int):
        raise MethodContractError("PBO partitions must be an integer")
    if partitions < 2 or partitions % 2:
        raise MethodContractError("PBO partitions must be an even integer of at least 2")
    if matrix.shape[0] % partitions:
        raise DataContractError("PBO requires equal partitions; row count must divide partitions")
    combination_count = math.comb(partitions, partitions // 2)
    if combination_count > max_combinations:
        raise MethodContractError(
            "PBO combination count exceeds max_combinations; reduce partitions or raise the "
            "explicit safety limit"
        )
    group_size = matrix.shape[0] // partitions
    partitioned = matrix.reshape(partitions, group_size, matrix.shape[1])
    partition_means = partitioned.mean(axis=1)
    centered = partitioned - partition_means[:, np.newaxis, :]
    partition_m2 = np.einsum("pgm,pgm->pm", centered, centered)
    rows: list[dict[str, JsonValue]] = []
    tie_count = 0
    all_groups = set(range(partitions))
    for combination_index, in_sample_groups in enumerate(
        combinations(range(partitions), partitions // 2)
    ):
        out_of_sample_groups = tuple(sorted(all_groups.difference(in_sample_groups)))
        in_sample_performance = _combined_partition_performance(
            partition_means,
            partition_m2,
            in_sample_groups,
            group_size=group_size,
            statistic=statistic,
        )
        out_of_sample_performance = _combined_partition_performance(
            partition_means,
            partition_m2,
            out_of_sample_groups,
            group_size=group_size,
            statistic=statistic,
        )
        best = np.flatnonzero(in_sample_performance == in_sample_performance.max())
        if best.size > 1:
            tie_count += 1
            if tie_break == "raise":
                raise DataContractError(
                    "PBO in-sample selection has a tie; use tie_break='first' only when the "
                    "declared strategy order is a defensible deterministic rule"
                )
        selected = int(best[0])
        rank = float(_average_ranks(out_of_sample_performance)[selected])
        relative_rank = rank / (matrix.shape[1] + 1.0)
        logit = math.log(relative_rank / (1.0 - relative_rank))
        rows.append(
            {
                "combination": combination_index,
                "in_sample_groups": tuple(in_sample_groups),
                "out_of_sample_groups": out_of_sample_groups,
                "selected_strategy": names[selected],
                "selected_strategy_index": selected,
                "in_sample_performance": float(in_sample_performance[selected]),
                "out_of_sample_performance": float(out_of_sample_performance[selected]),
                "out_of_sample_rank": rank,
                "relative_rank": relative_rank,
                "logit": logit,
                "underperformed_median": logit <= 0.0,
            }
        )
    pbo = sum(bool(row["underperformed_median"]) for row in rows) / len(rows)
    return pbo, rows, tie_count


def _native_pbo_for_partitions(
    matrix: FloatArray,
    names: tuple[str, ...],
    *,
    partitions: int,
    statistic: PBOStatistic,
    tie_break: PBOTieBreak,
    max_combinations: int,
    telemetry: dict[str, int | float | None] | None = None,
) -> tuple[float, list[dict[str, JsonValue]], int] | None:
    """Return compact native PBO output, or ``None`` when the symbol is unavailable."""

    if isinstance(partitions, bool) or not isinstance(partitions, int):
        raise MethodContractError("PBO partitions must be an integer")
    if partitions < 2 or partitions % 2:
        raise MethodContractError("PBO partitions must be an even integer of at least 2")
    if matrix.shape[0] % partitions:
        raise DataContractError("PBO requires equal partitions; row count must divide partitions")
    combination_count = math.comb(partitions, partitions // 2)
    if combination_count > max_combinations:
        raise MethodContractError(
            "PBO combination count exceeds max_combinations; reduce partitions or raise the "
            "explicit safety limit"
        )
    combination_tuples = tuple(combinations(range(partitions), partitions // 2))
    combination_groups: npt.NDArray[np.int64] = np.asarray(
        combination_tuples,
        dtype=np.int64,
    )
    try:
        from lacuna import _native
    except ImportError:
        return None
    if not hasattr(_native, "pbo_partition_splits"):
        return None

    normalized_matrix = readonly_float64_matrix(matrix, name="matrix")
    normalized_groups = readonly_int64_matrix(
        combination_groups,
        name="combination_groups",
    )
    native_matrix = normalized_matrix.values
    native_groups = normalized_groups.values
    kernel_started = time.perf_counter()
    try:
        raw = _native.pbo_partition_splits(
            native_matrix,
            native_groups,
            partitions,
            statistic,
        )
    except ValueError as error:
        raise DataContractError(str(error)) from error
    kernel_seconds = time.perf_counter() - kernel_started
    if len(raw) != 7:
        raise RuntimeError("native PBO reducer returned an invalid carrier")
    selected, in_performance, out_performance, ranks, logits, ties, underperformed = raw
    arrays = tuple(np.asarray(value) for value in raw)
    if any(value.shape != (combination_count,) for value in arrays):
        raise RuntimeError("native PBO reducer returned inconsistent output lengths")
    if not np.isfinite(in_performance).all() or not np.isfinite(out_performance).all():
        raise RuntimeError("native PBO reducer returned non-finite performance")
    if not np.isfinite(ranks).all() or not np.isfinite(logits).all():
        raise RuntimeError("native PBO reducer returned non-finite ranks")
    if np.any(selected < 0) or np.any(selected >= matrix.shape[1]):
        raise RuntimeError("native PBO reducer returned an invalid strategy index")
    if not np.isin(ties, (0, 1)).all() or not np.isin(underperformed, (0, 1)).all():
        raise RuntimeError("native PBO reducer returned an invalid status code")
    tie_count = int(ties.sum())
    if tie_count and tie_break == "raise":
        raise DataContractError(
            "PBO in-sample selection has a tie; use tie_break='first' only when the "
            "declared strategy order is a defensible deterministic rule"
        )

    projection_started = time.perf_counter()
    all_groups = set(range(partitions))
    rows: list[dict[str, JsonValue]] = []
    for combination_index, in_sample_groups in enumerate(combination_tuples):
        out_of_sample_groups = tuple(sorted(all_groups.difference(in_sample_groups)))
        selected_index = int(selected[combination_index])
        rank = float(ranks[combination_index])
        relative_rank = rank / (matrix.shape[1] + 1.0)
        logit = float(logits[combination_index])
        expected_logit = math.log(relative_rank / (1.0 - relative_rank))
        if not math.isclose(logit, expected_logit, rel_tol=1e-15, abs_tol=1e-15):
            raise RuntimeError("native PBO reducer returned an inconsistent rank logit")
        rows.append(
            {
                "combination": combination_index,
                "in_sample_groups": tuple(in_sample_groups),
                "out_of_sample_groups": out_of_sample_groups,
                "selected_strategy": names[selected_index],
                "selected_strategy_index": selected_index,
                "in_sample_performance": float(in_performance[combination_index]),
                "out_of_sample_performance": float(out_performance[combination_index]),
                "out_of_sample_rank": rank,
                "relative_rank": relative_rank,
                "logit": logit,
                "underperformed_median": bool(underperformed[combination_index]),
            }
        )
    pbo = float(np.mean(underperformed, dtype=np.float64))
    if telemetry is not None:
        input_bytes = int(native_matrix.nbytes + native_groups.nbytes)
        normalization_copy_bytes = normalized_matrix.copied_bytes + normalized_groups.copied_bytes
        moment_bytes = (
            partitions
            * matrix.shape[1]
            * (np.dtype(np.uintp).itemsize + 2 * np.dtype(np.float64).itemsize)
        )
        scratch_bytes = partitions * np.dtype(np.uint8).itemsize + (
            2 * matrix.shape[1] * np.dtype(np.float64).itemsize
        )
        telemetry["input_copy_bytes"] = int(telemetry.get("input_copy_bytes") or 0) + (
            normalization_copy_bytes + input_bytes
        )
        telemetry["output_copy_bytes"] = 0
        telemetry["temporary_workspace_bytes"] = max(
            int(telemetry.get("temporary_workspace_bytes") or 0),
            moment_bytes + scratch_bytes,
        )
        telemetry["result_projection_bytes"] = int(
            telemetry.get("result_projection_bytes") or 0
        ) + sum(int(value.nbytes) for value in arrays)
        telemetry["kernel"] = float(telemetry.get("kernel") or 0.0) + kernel_seconds
        telemetry["result_projection"] = float(telemetry.get("result_projection") or 0.0) + (
            time.perf_counter() - projection_started
        )
    return pbo, rows, tie_count


def _pbo_for_partitions(
    matrix: FloatArray,
    names: tuple[str, ...],
    *,
    partitions: int,
    statistic: PBOStatistic,
    tie_break: PBOTieBreak,
    max_combinations: int,
    backend: _PBOBackend,
    telemetry: dict[str, int | float | None] | None = None,
) -> tuple[float, list[dict[str, JsonValue]], int, str]:
    combination_count = (
        math.comb(partitions, partitions // 2)
        if isinstance(partitions, int) and not isinstance(partitions, bool) and partitions >= 2
        else 0
    )
    attempt_native = backend == "native" or (
        backend == "auto" and combination_count >= _PBO_NATIVE_CROSSOVER_COMBINATIONS
    )
    if attempt_native:
        native = _native_pbo_for_partitions(
            matrix,
            names,
            partitions=partitions,
            statistic=statistic,
            tie_break=tie_break,
            max_combinations=max_combinations,
            telemetry=telemetry,
        )
        if native is not None:
            return (*native, "rust_native")
        if backend == "native":
            raise RuntimeError("native PBO reducer is unavailable")
    reference = _pbo_for_partitions_reference(
        matrix,
        names,
        partitions=partitions,
        statistic=statistic,
        tie_break=tie_break,
        max_combinations=max_combinations,
    )
    return (*reference, "numpy_partition_moments")


def _probability_of_backtest_overfitting(
    data: object,
    *,
    strategy_columns: Sequence[str] | None = None,
    partitions: int = 8,
    statistic: PBOStatistic = "sharpe",
    partition_sensitivity: Sequence[int] | None = None,
    tie_break: PBOTieBreak = "raise",
    max_combinations: int = 20_000,
    backend: _PBOBackend,
    telemetry: dict[str, int | float | None] | None = None,
) -> AnalysisResult:
    if statistic not in {"mean", "sharpe"}:
        raise MethodContractError("statistic must be 'mean' or 'sharpe'")
    if tie_break not in {"raise", "first"}:
        raise MethodContractError("tie_break must be 'raise' or 'first'")
    if isinstance(max_combinations, bool) or not isinstance(max_combinations, int):
        raise MethodContractError("max_combinations must be an integer")
    if max_combinations < 1:
        raise MethodContractError("max_combinations must be positive")
    if backend not in {"auto", "reference", "native"}:
        raise MethodContractError("private PBO backend must be auto, reference, or native")
    normalization_started = time.perf_counter()
    matrix, names, source = _strategy_matrix(
        data,
        strategy_columns=strategy_columns,
        name="PBO",
    )
    if telemetry is not None:
        telemetry["normalization"] = time.perf_counter() - normalization_started
    counts = tuple(dict.fromkeys((partitions, *(partition_sensitivity or ()))))
    sensitivity_rows: list[dict[str, JsonValue]] = []
    main_rows: list[dict[str, JsonValue]] = []
    main_pbo = 0.0
    main_ties = 0
    selected_backends: set[str] = set()
    for count in counts:
        pbo, rows, tie_count, selected_backend = _pbo_for_partitions(
            matrix,
            names,
            partitions=count,
            statistic=statistic,
            tie_break=tie_break,
            max_combinations=max_combinations,
            backend=backend,
            telemetry=telemetry,
        )
        selected_backends.add(selected_backend)
        sensitivity_rows.append(
            {
                "partitions": count,
                "combinations": len(rows),
                "pbo": pbo,
                "selection_ties": tie_count,
            }
        )
        if count == partitions:
            main_pbo, main_rows, main_ties = pbo, rows, tie_count
    findings = (
        Finding(
            code="BACKTEST_OVERFITTING_ELEVATED" if main_pbo > 0.5 else "BACKTEST_OVERFITTING_LOW",
            title=(
                "Selected strategies often fail out of sample"
                if main_pbo > 0.5
                else "Selected strategies usually retain their relative rank"
            ),
            message=(
                "More than half of CSCV selections underperform the OOS median."
                if main_pbo > 0.5
                else "At most half of CSCV selections underperform the OOS median."
            ),
            state=FindingState.WARN if main_pbo > 0.5 else FindingState.PASS,
            severity=Severity.HIGH if main_pbo > 0.5 else Severity.INFO,
            category="backtest_overfitting",
            evidence={"pbo": main_pbo, "partitions": partitions},
        ),
    )
    warnings = [
        "PBO describes the supplied strategy family and partition design; it is not a "
        "universal false-discovery probability."
    ]
    if len(counts) == 1:
        warnings.append(
            "Provide partition_sensitivity to assess dependence on the CSCV partition count."
        )
    if main_ties:
        warnings.append(
            "In-sample ties were resolved by declared strategy order because tie_break='first'."
        )
    result_started = time.perf_counter()
    result = AnalysisResult(
        metadata=ResultMetadata(
            method="validation.probability_of_backtest_overfitting",
            method_version=1,
            parameters={
                "strategy_columns": names,
                "partitions": partitions,
                "statistic": statistic,
                "partition_sensitivity": counts,
                "tie_break": tie_break,
                "max_combinations": max_combinations,
                "partitioning": "equal_contiguous_synchronous_rows",
                "backend": (
                    next(iter(selected_backends))
                    if len(selected_backends) == 1
                    else "mixed_reference_native"
                ),
                "input": source,
            },
            input_fingerprint=fingerprint(matrix, namespace="pbo-input"),
        ),
        metrics={
            "pbo": main_pbo,
            "n_observations": int(matrix.shape[0]),
            "n_strategies": int(matrix.shape[1]),
            "n_partitions": partitions,
            "n_combinations": len(main_rows),
            "selection_ties": main_ties,
        },
        findings=findings,
        tables={
            "combinations": tuple(main_rows),
            "partition_sensitivity": tuple(sensitivity_rows),
        },
        warnings=tuple(warnings),
    )
    if telemetry is not None:
        telemetry["result_construction"] = time.perf_counter() - result_started
    return result


def probability_of_backtest_overfitting(
    data: object,
    *,
    strategy_columns: Sequence[str] | None = None,
    partitions: int = 8,
    statistic: PBOStatistic = "sharpe",
    partition_sensitivity: Sequence[int] | None = None,
    tie_break: PBOTieBreak = "raise",
    max_combinations: int = 20_000,
) -> AnalysisResult:
    """Estimate PBO with combinatorially symmetric cross-validation (CSCV).

    This consumes a synchronous ``T x N`` matrix of already-computed strategy
    performance, partitions its rows into equal chronological groups, performs
    every symmetric IS/OOS selection, and reports the selected strategy's OOS
    relative rank and logit for every combination. It is deliberately distinct
    from model-fitting CPCV in :mod:`lacuna.cv`.
    """

    return _probability_of_backtest_overfitting(
        data,
        strategy_columns=strategy_columns,
        partitions=partitions,
        statistic=statistic,
        partition_sensitivity=partition_sensitivity,
        tie_break=tie_break,
        max_combinations=max_combinations,
        backend="auto",
    )


def _expected_block_length(size: int, expected_block_length: int | None) -> int:
    resolved = (
        max(2, round(size ** (1.0 / 3.0)))
        if expected_block_length is None
        else expected_block_length
    )
    if isinstance(resolved, bool) or not isinstance(resolved, int):
        raise MethodContractError("expected_block_length must be an integer")
    if not 1 <= resolved <= size:
        raise MethodContractError("expected_block_length must be between 1 and sample size")
    return resolved


def _stationary_bootstrap_indices(
    *,
    size: int,
    expected_block_length: int,
    seed: int,
    method_version: int,
    replicate: int,
) -> npt.NDArray[np.intp]:
    rng = _replicate_rng(seed, method_version, replicate)
    restart_probability = 1.0 / expected_block_length
    indices: npt.NDArray[np.intp] = np.empty(size, dtype=np.intp)
    indices[0] = int(rng.integers(0, size))
    for position in range(1, size):
        if rng.random() < restart_probability:
            indices[position] = int(rng.integers(0, size))
        else:
            indices[position] = (indices[position - 1] + 1) % size
    return indices


def _joint_bootstrap_means(
    matrix: FloatArray,
    *,
    expected_block_length: int,
    resamples: int,
    seed: int,
    method_version: int,
) -> tuple[FloatArray, ResolvedExecutionBudget]:
    means = np.empty((resamples, matrix.shape[1]), dtype=np.float64)
    selected_workspace = matrix.shape[0] * matrix.shape[1] * np.dtype(np.float64).itemsize
    budget = resolve_execution_budget(
        total_items=resamples,
        required_fixed_allocation_bytes=means.nbytes + selected_workspace,
        per_item_workspace_bytes=matrix.shape[0] * np.dtype(np.intp).itemsize,
        backend="numpy_reference",
        dispatch_reason="bounded per-replicate joint mean reference reduction",
        configuration=get_config(),
    )
    for batch_start in range(0, resamples, budget.selected_batch_size):
        batch_end = min(resamples, batch_start + budget.selected_batch_size)
        for replicate in range(batch_start, batch_end):
            indices = _stationary_bootstrap_indices(
                size=matrix.shape[0],
                expected_block_length=expected_block_length,
                seed=seed,
                method_version=method_version,
                replicate=replicate,
            )
            means[replicate] = matrix[indices].mean(axis=0)
    return means, budget


def _resampling_configuration(
    *,
    size: int,
    expected_block_length: int | None,
    resamples: int,
    seed: int | None,
) -> tuple[int, int]:
    if isinstance(resamples, bool) or not isinstance(resamples, int):
        raise MethodContractError("resamples must be an integer")
    if resamples < 100:
        raise MethodContractError("resamples must be at least 100 for inferential output")
    return _expected_block_length(size, expected_block_length), _resolved_seed(seed)


def joint_stationary_bootstrap(
    data: object,
    *,
    strategy_columns: Sequence[str] | None = None,
    expected_block_length: int | None = None,
    resamples: int = 1_000,
    seed: int | None = None,
    store_distribution: bool = False,
) -> AnalysisResult:
    """Jointly bootstrap synchronous strategy means with random-length blocks.

    One stationary-bootstrap index path is shared by every strategy in each
    replicate. This preserves both within-series time dependence and
    cross-strategy dependence.
    """

    matrix, names, source = _strategy_matrix(
        data,
        strategy_columns=strategy_columns,
        name="joint stationary bootstrap",
    )
    block_length, resolved_seed = _resampling_configuration(
        size=matrix.shape[0],
        expected_block_length=expected_block_length,
        resamples=resamples,
        seed=seed,
    )
    distribution, execution_budget = _joint_bootstrap_means(
        matrix,
        expected_block_length=block_length,
        resamples=resamples,
        seed=resolved_seed,
        method_version=3,
    )
    observed_means = matrix.mean(axis=0)
    standard_errors = distribution.std(axis=0, ddof=1)
    centered = math.sqrt(matrix.shape[0]) * (distribution - observed_means)
    covariance = np.atleast_2d(np.cov(centered, rowvar=False, ddof=1))
    strategy_rows: list[dict[str, JsonValue]] = []
    for index, name in enumerate(names):
        strategy_rows.append(
            {
                "strategy": name,
                "mean": float(observed_means[index]),
                "bootstrap_mean": float(distribution[:, index].mean()),
                "bootstrap_standard_error": float(standard_errors[index]),
            }
        )
    covariance_rows: list[dict[str, JsonValue]] = []
    for row, first in enumerate(names):
        for column, second in enumerate(names):
            covariance_rows.append(
                {
                    "strategy": first,
                    "other_strategy": second,
                    "long_run_covariance": float(covariance[row, column]),
                }
            )
    tables: dict[str, JsonValue] = {
        "strategy_statistics": tuple(strategy_rows),
        "long_run_covariance": tuple(covariance_rows),
    }
    if store_distribution:
        distribution_rows: list[dict[str, JsonValue]] = []
        for replicate in range(resamples):
            for strategy, name in enumerate(names):
                distribution_rows.append(
                    {
                        "replicate": replicate,
                        "strategy": name,
                        "mean": float(distribution[replicate, strategy]),
                    }
                )
        tables["bootstrap_distribution"] = tuple(distribution_rows)
    return AnalysisResult(
        metadata=ResultMetadata(
            method="validation.joint_stationary_bootstrap",
            method_version=3,
            parameters={
                "strategy_columns": names,
                "expected_block_length": block_length,
                "stationary_restart_probability": 1.0 / block_length,
                "resamples": resamples,
                "joint_indices": True,
                "rng": "numpy.PCG64/SeedSequence",
                "substream_identity": "(seed, method_version=3, replicate)",
                "backend": execution_budget.backend,
                "input": source,
            },
            seed=resolved_seed,
            input_fingerprint=fingerprint(matrix, namespace="joint-bootstrap-input"),
        ),
        metrics={
            "n_observations": int(matrix.shape[0]),
            "n_strategies": int(matrix.shape[1]),
            "resamples": resamples,
            "monte_carlo_resolution": 1.0 / (resamples + 1.0),
        },
        tables=tables,
        warnings=(
            "Block-length sensitivity is part of the inferential design and should be reported.",
        ),
    )


def _bootstrap_p_value(distribution: FloatArray, observed: float) -> tuple[float, int]:
    exceedances = int(np.count_nonzero(distribution >= observed))
    return (exceedances + 1.0) / (distribution.size + 1.0), exceedances


def reality_check(
    data: object,
    *,
    strategy_columns: Sequence[str] | None = None,
    expected_block_length: int | None = None,
    resamples: int = 1_000,
    seed: int | None = None,
    store_distribution: bool = False,
) -> AnalysisResult:
    """Run White's Reality Check over a declared strategy family.

    Input cells are synchronous performance differentials versus one common
    benchmark, with positive values meaning that a candidate is better. The
    full matrix is resampled jointly with the stationary bootstrap.
    """

    matrix, names, source = _strategy_matrix(
        data,
        strategy_columns=strategy_columns,
        name="White Reality Check",
    )
    block_length, resolved_seed = _resampling_configuration(
        size=matrix.shape[0],
        expected_block_length=expected_block_length,
        resamples=resamples,
        seed=seed,
    )
    means = matrix.mean(axis=0)
    root_n = math.sqrt(matrix.shape[0])
    winner = int(np.argmax(means))
    observed = max(0.0, root_n * float(means[winner]))
    bootstrap_means, execution_budget = _joint_bootstrap_means(
        matrix,
        expected_block_length=block_length,
        resamples=resamples,
        seed=resolved_seed,
        method_version=4,
    )
    bootstrap_statistics = np.maximum(
        0.0,
        np.max(root_n * (bootstrap_means - means), axis=1),
    )
    p_value, exceedances = _bootstrap_p_value(bootstrap_statistics, observed)
    strategy_rows: tuple[JsonValue, ...] = tuple(
        {"strategy": name, "mean_differential": float(means[index])}
        for index, name in enumerate(names)
    )
    tables: dict[str, JsonValue] = {
        "strategy_statistics": strategy_rows,
        "distribution_summary": _distribution_summary(bootstrap_statistics),
    }
    if store_distribution:
        tables["bootstrap_distribution"] = frame_records(
            pl.DataFrame(
                {
                    "replicate": np.arange(resamples, dtype=np.int64),
                    "statistic": bootstrap_statistics,
                }
            )
        )
    significant = p_value <= 0.05 and observed > 0.0
    return AnalysisResult(
        metadata=ResultMetadata(
            method="validation.white_reality_check",
            method_version=4,
            parameters={
                "strategy_columns": names,
                "direction": "positive differential means candidate outperforms benchmark",
                "expected_block_length": block_length,
                "stationary_restart_probability": 1.0 / block_length,
                "resamples": resamples,
                "null": "no candidate has positive expected performance differential",
                "joint_indices": True,
                "finite_sample_p_value_correction": "(exceedances + 1) / (resamples + 1)",
                "rng": "numpy.PCG64/SeedSequence",
                "substream_identity": "(seed, method_version=4, replicate)",
                "backend": execution_budget.backend,
                "input": source,
            },
            seed=resolved_seed,
            input_fingerprint=fingerprint(matrix, namespace="reality-check-input"),
        ),
        metrics={
            "statistic": observed,
            "p_value": p_value,
            "exceedances": exceedances,
            "best_strategy": names[winner],
            "best_mean_differential": float(means[winner]),
            "n_observations": int(matrix.shape[0]),
            "n_strategies": int(matrix.shape[1]),
            "monte_carlo_resolution": 1.0 / (resamples + 1.0),
        },
        findings=(
            Finding(
                code=(
                    "REALITY_CHECK_SUPERIOR_CANDIDATE"
                    if significant
                    else "REALITY_CHECK_NO_SUPERIOR_CANDIDATE"
                ),
                title=(
                    "A candidate survives the Reality Check"
                    if significant
                    else "No candidate survives the Reality Check"
                ),
                message=(
                    "The best candidate rejects the family-wise no-superiority null."
                    if significant
                    else "The declared family does not reject the no-superiority null at 5%."
                ),
                state=FindingState.PASS if significant else FindingState.WARN,
                severity=Severity.INFO if significant else Severity.MEDIUM,
                category="data_snooping",
                evidence={"p_value": p_value, "best_strategy": names[winner]},
            ),
        ),
        tables=tables,
        warnings=(
            "White's least-favorable null can be conservative when many poor alternatives "
            "are included.",
            "Block-length sensitivity should be checked before treating the p-value as stable.",
        ),
    )


def _stationary_long_run_variances(
    matrix: FloatArray,
    *,
    expected_block_length: int,
) -> FloatArray:
    size = matrix.shape[0]
    centered = matrix - matrix.mean(axis=0)
    transform_size = 2 * size
    transformed = np.fft.rfft(centered, n=transform_size, axis=0)
    autocovariances = np.fft.irfft(
        np.conjugate(transformed) * transformed,
        n=transform_size,
        axis=0,
    )[:size]
    autocovariances /= size
    restart_probability = 1.0 / expected_block_length
    lags = np.arange(1, size, dtype=np.float64)
    kernel = ((size - lags) / size) * (1.0 - restart_probability) ** lags + (lags / size) * (
        1.0 - restart_probability
    ) ** (size - lags)
    variances = autocovariances[0] + 2.0 * np.sum(
        kernel[:, np.newaxis] * autocovariances[1:],
        axis=0,
    )
    return np.asarray(variances, dtype=np.float64)


def superior_predictive_ability(
    data: object,
    *,
    strategy_columns: Sequence[str] | None = None,
    expected_block_length: int | None = None,
    resamples: int = 1_000,
    seed: int | None = None,
    store_distribution: bool = False,
) -> AnalysisResult:
    """Run Hansen's studentized Superior Predictive Ability test.

    Returns the lower, consistent, and upper bootstrap p-values. Input cells
    are synchronous performance differentials versus one common benchmark;
    positive values mean that a candidate is better.
    """

    matrix, names, source = _strategy_matrix(
        data,
        strategy_columns=strategy_columns,
        name="Hansen SPA",
    )
    block_length, resolved_seed = _resampling_configuration(
        size=matrix.shape[0],
        expected_block_length=expected_block_length,
        resamples=resamples,
        seed=seed,
    )
    variances = _stationary_long_run_variances(
        matrix,
        expected_block_length=block_length,
    )
    invalid = np.flatnonzero(~np.isfinite(variances) | (variances <= 0.0))
    if invalid.size:
        invalid_names = ", ".join(names[int(index)] for index in invalid)
        raise DataContractError(
            "SPA requires positive finite stationary-bootstrap long-run variance for every "
            f"strategy; invalid: {invalid_names}"
        )
    scales = np.sqrt(variances)
    means = matrix.mean(axis=0)
    root_n = math.sqrt(matrix.shape[0])
    standardized = root_n * means / scales
    observed = max(0.0, float(standardized.max()))
    winner = int(np.argmax(standardized))
    log_log = math.log(math.log(matrix.shape[0]))
    if log_log <= 0.0:
        raise DataContractError("SPA requires enough observations for log(log(n)) to be positive")
    consistent_thresholds = -scales * math.sqrt(2.0 * log_log / matrix.shape[0])
    recenterings = {
        "lower": np.maximum(0.0, means),
        "consistent": means * (means >= consistent_thresholds),
        "upper": means,
    }
    bootstrap_means, execution_budget = _joint_bootstrap_means(
        matrix,
        expected_block_length=block_length,
        resamples=resamples,
        seed=resolved_seed,
        method_version=5,
    )
    distributions: dict[str, FloatArray] = {}
    p_values: dict[str, float] = {}
    exceedance_counts: dict[str, int] = {}
    for recentering, location in recenterings.items():
        distribution = np.maximum(
            0.0,
            np.max(root_n * (bootstrap_means - location) / scales, axis=1),
        )
        distributions[recentering] = distribution
        p_value, exceedances = _bootstrap_p_value(distribution, observed)
        p_values[recentering] = p_value
        exceedance_counts[recentering] = exceedances

    strategy_rows: list[dict[str, JsonValue]] = []
    for index, name in enumerate(names):
        strategy_rows.append(
            {
                "strategy": name,
                "mean_differential": float(means[index]),
                "long_run_variance": float(variances[index]),
                "long_run_standard_deviation": float(scales[index]),
                "standardized_mean": float(standardized[index]),
                "consistent_threshold": float(consistent_thresholds[index]),
                "lower_recentering": float(recenterings["lower"][index]),
                "consistent_recentering": float(recenterings["consistent"][index]),
                "upper_recentering": float(recenterings["upper"][index]),
            }
        )
    p_value_rows = tuple(
        {
            "recentering": recentering,
            "p_value": p_values[recentering],
            "exceedances": exceedance_counts[recentering],
        }
        for recentering in ("lower", "consistent", "upper")
    )
    tables: dict[str, JsonValue] = {
        "strategy_statistics": tuple(strategy_rows),
        "p_values": p_value_rows,
        "consistent_distribution_summary": _distribution_summary(distributions["consistent"]),
    }
    if store_distribution:
        tables["bootstrap_distribution"] = tuple(
            {
                "replicate": replicate,
                "lower": float(distributions["lower"][replicate]),
                "consistent": float(distributions["consistent"][replicate]),
                "upper": float(distributions["upper"][replicate]),
            }
            for replicate in range(resamples)
        )
    significant = p_values["consistent"] <= 0.05 and observed > 0.0
    return AnalysisResult(
        metadata=ResultMetadata(
            method="validation.hansen_spa",
            method_version=5,
            parameters={
                "strategy_columns": names,
                "direction": "positive differential means candidate outperforms benchmark",
                "expected_block_length": block_length,
                "stationary_restart_probability": 1.0 / block_length,
                "long_run_variance": "Hansen stationary-bootstrap population kernel",
                "resamples": resamples,
                "null": "no candidate has positive expected performance differential",
                "recentering": ("lower", "consistent", "upper"),
                "joint_indices": True,
                "finite_sample_p_value_correction": "(exceedances + 1) / (resamples + 1)",
                "rng": "numpy.PCG64/SeedSequence",
                "substream_identity": "(seed, method_version=5, replicate)",
                "backend": execution_budget.backend,
                "input": source,
            },
            seed=resolved_seed,
            input_fingerprint=fingerprint(matrix, namespace="spa-input"),
        ),
        metrics={
            "statistic": observed,
            "p_value_lower": p_values["lower"],
            "p_value_consistent": p_values["consistent"],
            "p_value_upper": p_values["upper"],
            "best_strategy": names[winner],
            "best_standardized_mean": float(standardized[winner]),
            "n_observations": int(matrix.shape[0]),
            "n_strategies": int(matrix.shape[1]),
            "monte_carlo_resolution": 1.0 / (resamples + 1.0),
        },
        findings=(
            Finding(
                code=("SPA_SUPERIOR_CANDIDATE" if significant else "SPA_NO_SUPERIOR_CANDIDATE"),
                title=(
                    "A candidate survives Hansen SPA"
                    if significant
                    else "No candidate survives Hansen SPA"
                ),
                message=(
                    "The studentized family rejects the no-superiority null."
                    if significant
                    else "The declared family does not reject the no-superiority null at 5%."
                ),
                state=FindingState.PASS if significant else FindingState.WARN,
                severity=Severity.INFO if significant else Severity.MEDIUM,
                category="data_snooping",
                evidence={
                    "consistent_p_value": p_values["consistent"],
                    "best_strategy": names[winner],
                },
            ),
        ),
        tables=tables,
        warnings=(
            "SPA asymptotics require a stationary weakly dependent differential process.",
            "Block-length sensitivity should be checked before treating the p-values as stable.",
        ),
    )


__all__ = [
    "PBOStatistic",
    "PBOTieBreak",
    "PermutationAlternative",
    "PermutationScheme",
    "PermutationStatistic",
    "joint_stationary_bootstrap",
    "permutation_test",
    "probability_of_backtest_overfitting",
    "reality_check",
    "sharpe_inference",
    "superior_predictive_ability",
]
