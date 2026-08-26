"""Validated decay inference over stored signal-decay evidence."""

from __future__ import annotations

import math
import secrets
from collections.abc import Mapping, Sequence
from typing import Literal, TypeAlias, cast

import numpy as np
import numpy.typing as npt

from lacuna._resampling import stationary_bootstrap_indices
from lacuna.exceptions import MethodContractError
from lacuna.types import (
    AnalysisResult,
    Finding,
    FindingState,
    JsonValue,
    ResultMetadata,
    Severity,
)

FloatArray: TypeAlias = npt.NDArray[np.float64]
Direction = Literal["positive", "negative"]


def _horizon_value(value: object) -> float:
    if isinstance(value, bool):
        raise MethodContractError("decay horizons must be positive observation counts")
    if isinstance(value, int | float):
        parsed = float(value)
    elif isinstance(value, str) and value.upper().endswith("D"):
        try:
            parsed = float(value[:-1])
        except ValueError as error:
            raise MethodContractError(
                f"decay horizon {value!r} is not a trading-observation count"
            ) from error
    else:
        raise MethodContractError(f"decay horizon {value!r} is not a trading-observation count")
    if not math.isfinite(parsed) or parsed <= 0.0:
        raise MethodContractError("decay horizons must be finite and positive")
    return parsed


def _curve(horizon: FloatArray, amplitude: float, tau: float) -> FloatArray:
    return amplitude * np.exp(-horizon / tau)


def _result_without_half_life(
    decay_result: AnalysisResult,
    *,
    metric: str,
    expected_direction: Direction,
    confidence: float,
    resamples: int,
    expected_block_length: float | None,
    seed: int | None,
    minimum_r_squared: float,
    state: FindingState,
    code: str,
    reason: str,
    n_horizons: int,
    n_common_periods: int,
    candidate_amplitude: float | None = None,
    candidate_tau: float | None = None,
    r_squared: float | None = None,
    root_entropy: int | None = None,
    fit_rows: tuple[JsonValue, ...] = (),
) -> AnalysisResult:
    return AnalysisResult(
        metadata=ResultMetadata(
            method="signal.fit_decay",
            method_version=1,
            parameters={
                "source_method": decay_result.metadata.method,
                "metric": metric,
                "expected_direction": expected_direction,
                "model": "exponential",
                "confidence": confidence,
                "resamples": resamples,
                "expected_block_length": expected_block_length,
                "seed": seed,
                "root_entropy": root_entropy,
                "substream_identity": (
                    "SeedSequence(root_entropy).spawn(1)[0]" if root_entropy is not None else None
                ),
                "minimum_r_squared": minimum_r_squared,
                "optimizer": "scipy.optimize.curve_fit",
                "bounds": "amplitude>0,tau>0",
            },
        ),
        metrics={
            "amplitude": candidate_amplitude,
            "tau": candidate_tau,
            "half_life": None,
            "half_life_lower": None,
            "half_life_upper": None,
            "r_squared": r_squared,
            "n_horizons": n_horizons,
            "n_common_periods": n_common_periods,
            "successful_resamples": 0,
        },
        findings=(
            Finding(
                code=code,
                title="Decay half-life is not identified",
                message=reason,
                state=state,
                severity=Severity.MEDIUM,
                category="statistical_validity",
                evidence={
                    "n_horizons": n_horizons,
                    "n_common_periods": n_common_periods,
                    "reason": reason,
                },
            ),
        ),
        tables={"decay_fit": fit_rows},
    )


def fit_decay(
    decay_result: AnalysisResult,
    *,
    metric: str = "mean_ic",
    expected_direction: Direction = "positive",
    model: Literal["exponential"] = "exponential",
    confidence: float = 0.95,
    resamples: int = 2_000,
    expected_block_length: float | None = None,
    seed: int | None = None,
    minimum_r_squared: float = 0.5,
) -> AnalysisResult:
    """Fit an identifiable positive exponential curve with joint period resampling."""

    if (
        not isinstance(decay_result, AnalysisResult)
        or decay_result.metadata.method != "signal.decay"
    ):
        raise MethodContractError("decay_result must be an AnalysisResult from signal.decay")
    if expected_direction not in {"positive", "negative"}:
        raise MethodContractError("expected_direction must be 'positive' or 'negative'")
    if model != "exponential":
        raise MethodContractError("model must be 'exponential'")
    if not 0.0 < confidence < 1.0:
        raise MethodContractError("confidence must be between zero and one")
    if resamples < 100:
        raise MethodContractError("resamples must be at least 100")
    if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int) or seed < 0):
        raise MethodContractError("seed must be a non-negative integer")
    if not 0.0 <= minimum_r_squared <= 1.0:
        raise MethodContractError("minimum_r_squared must be between zero and one")
    if expected_block_length is not None and (
        not math.isfinite(float(expected_block_length)) or expected_block_length < 1.0
    ):
        raise MethodContractError("expected_block_length must be finite and at least one")

    table_name: str
    value_field: str
    if metric == "mean_ic":
        table_name, value_field = "ic_by_period_horizon", "ic"
    elif metric in {"mean_top_bottom_spread", "mean_spread"}:
        table_name, value_field = "spread_by_period_horizon", "spread"
    else:
        raise MethodContractError(
            "metric must be 'mean_ic', 'mean_spread', or 'mean_top_bottom_spread'"
        )
    if table_name not in decay_result.tables:
        return _result_without_half_life(
            decay_result,
            metric=metric,
            expected_direction=expected_direction,
            confidence=confidence,
            resamples=resamples,
            expected_block_length=expected_block_length,
            seed=seed,
            minimum_r_squared=minimum_r_squared,
            state=FindingState.UNKNOWN,
            code="DECAY_JOINT_PERIOD_EVIDENCE_MISSING",
            reason=f"source evidence does not contain {table_name}",
            n_horizons=0,
            n_common_periods=0,
        )
    records = decay_result.table(table_name)
    if not isinstance(records, list) or not all(isinstance(row, Mapping) for row in records):
        raise MethodContractError(f"{table_name} must contain row records")
    period_values: dict[object, dict[float, float]] = {}
    horizon_labels: dict[float, JsonValue] = {}
    direction = 1.0 if expected_direction == "positive" else -1.0
    for row in cast(Sequence[Mapping[str, object]], records):
        horizon = _horizon_value(row.get("horizon"))
        period = row.get("observation_time")
        raw_value = row.get(value_field)
        if period is None or not isinstance(raw_value, int | float) or isinstance(raw_value, bool):
            continue
        value = direction * float(raw_value)
        if not math.isfinite(value):
            continue
        values_for_period = period_values.setdefault(period, {})
        if horizon in values_for_period:
            raise MethodContractError("joint decay evidence contains duplicate period/horizon rows")
        values_for_period[horizon] = value
        horizon_labels[horizon] = cast(JsonValue, row.get("horizon"))
    horizons = tuple(sorted(horizon_labels))
    eligible_periods = [
        period for period, values in period_values.items() if set(values) == set(horizons)
    ]
    if all(
        isinstance(period, int | float) and not isinstance(period, bool)
        for period in eligible_periods
    ):
        common_periods = tuple(
            sorted(eligible_periods, key=lambda period: float(cast(float, period)))
        )
    elif all(isinstance(period, str) for period in eligible_periods):
        common_periods = tuple(sorted(eligible_periods, key=lambda period: cast(str, period)))
    else:
        raise MethodContractError(
            "joint decay periods must use one ordered numeric or serialized temporal type"
        )
    if len(horizons) < 4 or len(common_periods) < 20:
        return _result_without_half_life(
            decay_result,
            metric=metric,
            expected_direction=expected_direction,
            confidence=confidence,
            resamples=resamples,
            expected_block_length=expected_block_length,
            seed=seed,
            minimum_r_squared=minimum_r_squared,
            state=FindingState.UNKNOWN,
            code="DECAY_SUPPORT_INSUFFICIENT",
            reason="at least four horizons and twenty jointly observed periods are required",
            n_horizons=len(horizons),
            n_common_periods=len(common_periods),
        )
    matrix: FloatArray = np.asarray(
        [[period_values[period][horizon] for horizon in horizons] for period in common_periods],
        dtype=np.float64,
    )
    means = matrix.mean(axis=0)
    if np.any(means <= 0.0):
        return _result_without_half_life(
            decay_result,
            metric=metric,
            expected_direction=expected_direction,
            confidence=confidence,
            resamples=resamples,
            expected_block_length=expected_block_length,
            seed=seed,
            minimum_r_squared=minimum_r_squared,
            state=FindingState.WARN,
            code="DECAY_DIRECTION_INVALID",
            reason="every direction-adjusted horizon mean must be positive",
            n_horizons=len(horizons),
            n_common_periods=len(common_periods),
        )
    try:
        import scipy  # type: ignore[import-untyped]
        from scipy.optimize import curve_fit  # type: ignore[import-untyped]
    except ImportError as error:
        raise MethodContractError(
            "fit_decay requires SciPy; install the 'statistics' extra with lacuna[statistics]"
        ) from error

    x: FloatArray = np.asarray(horizons, dtype=np.float64)
    tau_upper = float(x.max() * 1_000.0)
    initial = (float(means.max()), float(np.median(x)))

    def fit(values: FloatArray) -> tuple[float, float]:
        parameters, _ = curve_fit(
            _curve,
            x,
            values,
            p0=initial,
            bounds=((np.finfo(np.float64).eps, np.finfo(np.float64).eps), (np.inf, tau_upper)),
            maxfev=20_000,
        )
        return float(parameters[0]), float(parameters[1])

    try:
        amplitude, tau = fit(means)
    except (RuntimeError, ValueError, FloatingPointError) as error:
        return _result_without_half_life(
            decay_result,
            metric=metric,
            expected_direction=expected_direction,
            confidence=confidence,
            resamples=resamples,
            expected_block_length=expected_block_length,
            seed=seed,
            minimum_r_squared=minimum_r_squared,
            state=FindingState.WARN,
            code="DECAY_OPTIMIZATION_FAILED",
            reason=f"positive exponential optimization failed: {type(error).__name__}",
            n_horizons=len(horizons),
            n_common_periods=len(common_periods),
        )
    fitted: FloatArray = _curve(x, amplitude, tau)
    residual_sum = float(np.sum((means - fitted) ** 2))
    total_sum = float(np.sum((means - means.mean()) ** 2))
    r_squared = 1.0 - residual_sum / total_sum if total_sum > 0.0 else 1.0
    candidate_fit_rows: tuple[JsonValue, ...] = tuple(
        {
            "horizon": horizon_labels[horizon],
            "horizon_observations": horizon,
            "direction_adjusted_mean": float(observed),
            "fitted_value": float(predicted),
            "residual": float(observed - predicted),
        }
        for horizon, observed, predicted in zip(horizons, means, fitted, strict=True)
    )
    if tau >= tau_upper * 0.999 or r_squared < minimum_r_squared:
        reason = (
            "optimizer reached the tau upper bound"
            if tau >= tau_upper * 0.999
            else "fit quality is below minimum_r_squared"
        )
        return _result_without_half_life(
            decay_result,
            metric=metric,
            expected_direction=expected_direction,
            confidence=confidence,
            resamples=resamples,
            expected_block_length=expected_block_length,
            seed=seed,
            minimum_r_squared=minimum_r_squared,
            state=FindingState.WARN,
            code="DECAY_FIT_NOT_IDENTIFIABLE",
            reason=reason,
            n_horizons=len(horizons),
            n_common_periods=len(common_periods),
            candidate_amplitude=amplitude,
            candidate_tau=tau,
            r_squared=r_squared,
            fit_rows=candidate_fit_rows,
        )

    block_length = (
        max(2.0, round(len(common_periods) ** (1.0 / 3.0)))
        if expected_block_length is None
        else float(expected_block_length)
    )
    if not math.isfinite(block_length) or block_length < 1.0:
        raise MethodContractError("expected_block_length must be finite and at least one")
    root_entropy = seed if seed is not None else secrets.randbits(128)
    seed_sequence = np.random.SeedSequence(root_entropy)
    child = seed_sequence.spawn(1)[0]
    rng = np.random.default_rng(child)
    indices = stationary_bootstrap_indices(
        len(common_periods),
        resamples=resamples,
        expected_block_length=block_length,
        rng=rng,
    )
    bootstrap_half_lives: list[float] = []
    for sample in indices:
        sampled_means = matrix[sample].mean(axis=0)
        if np.any(sampled_means <= 0.0):
            continue
        try:
            _, sampled_tau = fit(sampled_means)
        except (RuntimeError, ValueError, FloatingPointError):
            continue
        if sampled_tau < tau_upper * 0.999 and math.isfinite(sampled_tau):
            bootstrap_half_lives.append(sampled_tau * math.log(2.0))
    required_successes = math.ceil(resamples * 0.8)
    if len(bootstrap_half_lives) < required_successes:
        return _result_without_half_life(
            decay_result,
            metric=metric,
            expected_direction=expected_direction,
            confidence=confidence,
            resamples=resamples,
            expected_block_length=block_length,
            seed=seed,
            minimum_r_squared=minimum_r_squared,
            state=FindingState.WARN,
            code="DECAY_BOOTSTRAP_UNSTABLE",
            reason="fewer than 80% of bootstrap fits were identifiable",
            n_horizons=len(horizons),
            n_common_periods=len(common_periods),
            candidate_amplitude=amplitude,
            candidate_tau=tau,
            r_squared=r_squared,
            root_entropy=root_entropy,
            fit_rows=candidate_fit_rows,
        )
    alpha = 1.0 - confidence
    interval: FloatArray = np.quantile(
        np.asarray(bootstrap_half_lives, dtype=np.float64),
        [alpha / 2.0, 1.0 - alpha / 2.0],
    )
    half_life = tau * math.log(2.0)
    return AnalysisResult(
        metadata=ResultMetadata(
            method="signal.fit_decay",
            method_version=1,
            parameters={
                "source_method": decay_result.metadata.method,
                "metric": metric,
                "expected_direction": expected_direction,
                "model": model,
                "confidence": confidence,
                "resamples": resamples,
                "expected_block_length": block_length,
                "seed": seed,
                "root_entropy": root_entropy,
                "substream_identity": "SeedSequence(root_entropy).spawn(1)[0]",
                "minimum_r_squared": minimum_r_squared,
                "optimizer": "scipy.optimize.curve_fit",
                "optimizer_maxfev": 20_000,
                "bounds": {"amplitude": (0.0, None), "tau": (0.0, tau_upper)},
                "scipy_version": scipy.__version__,
            },
        ),
        metrics={
            "amplitude": amplitude,
            "tau": tau,
            "half_life": half_life,
            "half_life_lower": float(interval[0]),
            "half_life_upper": float(interval[1]),
            "r_squared": r_squared,
            "n_horizons": len(horizons),
            "n_common_periods": len(common_periods),
            "successful_resamples": len(bootstrap_half_lives),
        },
        findings=(
            Finding(
                code="DECAY_HALF_LIFE_IDENTIFIED",
                title="Decay half-life is identified under the declared model",
                message=(
                    "The joint-period exponential fit passed support, direction, and fit gates."
                ),
                state=FindingState.PASS,
                severity=Severity.INFO,
                category="statistical_validity",
                evidence={
                    "half_life": half_life,
                    "r_squared": r_squared,
                    "successful_resamples": len(bootstrap_half_lives),
                },
            ),
        ),
        tables={"decay_fit": candidate_fit_rows},
        warnings=(
            "Half-life is conditional on a positive exponential model and is measured in trading "
            "observations.",
        ),
    )


__all__ = ["fit_decay"]
