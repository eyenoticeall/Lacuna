from __future__ import annotations

import numpy as np
import polars as pl

from lacuna.validation import bootstrap, permutation_test, sharpe_inference


def _ar1(generator: np.random.Generator, size: int, persistence: float) -> np.ndarray:
    values = np.empty(size)
    values[0] = generator.normal()
    for index in range(1, size):
        values[index] = (
            persistence * values[index - 1] + np.sqrt(1.0 - persistence**2) * generator.normal()
        )
    return values


def _pearson_rejections(frames: list[pl.DataFrame], **options: object) -> int:
    return sum(
        int(
            float(
                permutation_test(
                    frame,
                    paired_with="paired",
                    statistic="pearson",
                    permutations=199,
                    seed=seed,
                    **options,  # type: ignore[arg-type]
                ).metrics["p_value"]  # type: ignore[arg-type]
            )
            <= 0.05
        )
        for seed, frame in enumerate(frames)
    )


# Deterministic calibration guards, not exact finite-sample claims. Each pairs the
# dependence-aware scheme with the naive one it must beat, so an implementation that
# silently degrades to the naive behavior fails. Nominal null rejection is two of forty.


def test_block_permutation_holds_null_size_where_unrestricted_permutation_fails() -> None:
    # Two independent persistent series are spuriously correlated in-sample; shuffling
    # individual observations destroys that dependence and over-rejects.
    frames = []
    for simulation in range(40):
        generator = np.random.default_rng(31_000 + simulation)
        frames.append(
            pl.DataFrame(
                {
                    "time": np.arange(300),
                    "value": _ar1(generator, 300, 0.8),
                    "paired": _ar1(generator, 300, 0.8),
                }
            )
        )

    assert _pearson_rejections(frames, scheme="unrestricted") >= 8
    assert _pearson_rejections(frames, scheme="block", block_length=25) <= 6


def test_within_date_permutation_holds_null_size_under_a_shared_date_effect() -> None:
    frames = []
    for simulation in range(40):
        generator = np.random.default_rng(32_000 + simulation)
        date_effect = np.repeat(2.0 * generator.normal(size=30), 10)
        frames.append(
            pl.DataFrame(
                {
                    "time": np.repeat(np.arange(30), 10),
                    "value": date_effect + generator.normal(size=300),
                    "paired": date_effect + generator.normal(size=300),
                }
            )
        )

    assert _pearson_rejections(frames, scheme="unrestricted") >= 30
    assert _pearson_rejections(frames, scheme="within_date") <= 6


def test_deflated_sharpe_discounts_the_best_of_many_null_strategies() -> None:
    psr_passes = 0
    dsr_passes = 0
    for simulation in range(40):
        generator = np.random.default_rng(33_000 + simulation)
        returns = generator.normal(0.0, 0.01, size=(250, 50))
        sharpes = returns.mean(axis=0) / returns.std(axis=0, ddof=1)
        best = int(np.argmax(sharpes))
        result = sharpe_inference(
            pl.DataFrame({"value": returns[:, best]}),
            trial_sharpes=sharpes.tolist(),
        )
        psr_passes += int(float(result.metrics["probabilistic_sharpe_ratio"]) >= 0.95)  # type: ignore[arg-type]
        dsr_passes += int(float(result.metrics["deflated_sharpe_ratio"]) >= 0.95)  # type: ignore[arg-type]

    # Selecting the maximum of 50 zero-edge strategies makes the undeflated PSR look
    # conclusive; DSR must remove that selection effect.
    assert psr_passes >= 25
    assert dsr_passes <= 2


def _interval_misses(samples: list[np.ndarray], **options: object) -> int:
    misses = 0
    for seed, values in enumerate(samples):
        metrics = bootstrap(
            values,
            resamples=400,
            confidence_level=0.90,
            seed=seed,
            use_native=False,
            **options,  # type: ignore[arg-type]
        ).metrics
        lower = float(metrics["confidence_lower"])  # type: ignore[arg-type]
        upper = float(metrics["confidence_upper"])  # type: ignore[arg-type]
        misses += int(not lower <= 0.0 <= upper)
    return misses


def test_iid_circular_and_stationary_bootstrap_intervals_have_reasonable_coverage() -> None:
    independent = [np.random.default_rng(34_000 + index).normal(size=150) for index in range(40)]
    dependent = [_ar1(np.random.default_rng(35_000 + index), 150, 0.5) for index in range(40)]

    # Nominal misses are four of forty; a dependence-blind interval misses far more often.
    ignored_dependence = _interval_misses(dependent, method="iid")
    assert _interval_misses(independent, method="iid") <= 8
    assert _interval_misses(dependent, method="circular", block_length=10) <= 11
    assert _interval_misses(dependent, method="stationary", expected_block_length=10) <= 11
    assert ignored_dependence >= 14
