from __future__ import annotations

import math

import numpy as np
import pytest

from lacuna.validation import reality_check, superior_predictive_ability


def _stationary_indices(
    size: int,
    block_length: int,
    seed: int,
    method_version: int,
    replicate: int,
) -> np.ndarray:
    rng = np.random.default_rng(np.random.SeedSequence([seed, method_version, replicate]))
    indices = np.empty(size, dtype=np.intp)
    indices[0] = rng.integers(0, size)
    for position in range(1, size):
        if rng.random() < 1.0 / block_length:
            indices[position] = rng.integers(0, size)
        else:
            indices[position] = (indices[position - 1] + 1) % size
    return indices


def _direct_hansen_variances(matrix: np.ndarray, block_length: int) -> np.ndarray:
    size = matrix.shape[0]
    means = matrix.mean(axis=0)
    result = np.empty(matrix.shape[1])
    for strategy in range(matrix.shape[1]):
        centered = matrix[:, strategy] - means[strategy]
        variance = float(np.dot(centered, centered) / size)
        for lag in range(1, size):
            covariance = float(np.dot(centered[:-lag], centered[lag:]) / size)
            kernel = (
                (size - lag) / size * (1.0 - 1.0 / block_length) ** lag
                + lag / size * (1.0 - 1.0 / block_length) ** (size - lag)
            )
            variance += 2.0 * kernel * covariance
        result[strategy] = variance
    return result


def test_reality_check_matches_an_independent_literal_reference() -> None:
    rng = np.random.default_rng(10)
    matrix = rng.normal(size=(24, 3))
    matrix[:, 0] += 0.25
    block_length = 4
    resamples = 100
    seed = 91
    result = reality_check(
        matrix,
        expected_block_length=block_length,
        resamples=resamples,
        seed=seed,
        store_distribution=True,
    )

    means = matrix.mean(axis=0)
    root_n = math.sqrt(matrix.shape[0])
    observed = max(0.0, float(np.max(root_n * means)))
    reference = []
    for replicate in range(resamples):
        indices = _stationary_indices(
            matrix.shape[0], block_length, seed, 4, replicate
        )
        bootstrap_means = matrix[indices].mean(axis=0)
        reference.append(max(0.0, float(np.max(root_n * (bootstrap_means - means)))))
    exceedances = sum(value >= observed for value in reference)

    observed_distribution = [
        row["statistic"] for row in result.table("bootstrap_distribution")
    ]
    assert observed_distribution == pytest.approx(reference, abs=1e-14)
    assert result.metrics["statistic"] == pytest.approx(observed)
    assert result.metrics["p_value"] == (exceedances + 1) / (resamples + 1)


def test_hansen_spa_matches_the_paper_equations_and_direct_kernel() -> None:
    rng = np.random.default_rng(13)
    matrix = rng.normal(size=(32, 4))
    matrix[:, 0] += 0.2
    matrix[:, 2] -= 0.7
    block_length = 5
    resamples = 100
    seed = 17
    result = superior_predictive_ability(
        matrix,
        expected_block_length=block_length,
        resamples=resamples,
        seed=seed,
        store_distribution=True,
    )

    size = matrix.shape[0]
    root_n = math.sqrt(size)
    means = matrix.mean(axis=0)
    variances = _direct_hansen_variances(matrix, block_length)
    scales = np.sqrt(variances)
    observed = max(0.0, float(np.max(root_n * means / scales)))
    threshold = -scales * math.sqrt(2.0 * math.log(math.log(size)) / size)
    recenterings = {
        "lower": np.maximum(0.0, means),
        "consistent": means * (means >= threshold),
        "upper": means,
    }
    reference = {name: [] for name in recenterings}
    for replicate in range(resamples):
        indices = _stationary_indices(size, block_length, seed, 5, replicate)
        bootstrap_means = matrix[indices].mean(axis=0)
        for name, recentering in recenterings.items():
            statistic = max(
                0.0,
                float(np.max(root_n * (bootstrap_means - recentering) / scales)),
            )
            reference[name].append(statistic)

    strategy_rows = result.table("strategy_statistics")
    assert [row["long_run_variance"] for row in strategy_rows] == pytest.approx(
        variances,
        abs=1e-12,
    )
    assert result.metrics["statistic"] == pytest.approx(observed)
    distribution_rows = result.table("bootstrap_distribution")
    for name in recenterings:
        assert [row[name] for row in distribution_rows] == pytest.approx(
            reference[name],
            abs=1e-12,
        )
        exceedances = sum(value >= observed for value in reference[name])
        assert result.metrics[f"p_value_{name}"] == (exceedances + 1) / (resamples + 1)
