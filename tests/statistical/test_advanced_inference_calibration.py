from __future__ import annotations

import numpy as np

from lacuna.validation import (
    permutation_test,
    probability_of_backtest_overfitting,
    sharpe_inference,
)


def test_sign_flip_and_psr_have_reasonable_fixed_seed_null_size() -> None:
    rng = np.random.default_rng(831)
    permutation_rejections = 0
    psr_rejections = 0
    simulations = 50
    for simulation in range(simulations):
        values = rng.normal(size=40)
        permutation = permutation_test(
            values,
            permutations=199,
            alternative="greater",
            seed=simulation,
        )
        sharpe = sharpe_inference(values, confidence_level=0.95)
        permutation_rejections += permutation.metrics["p_value"] <= 0.05
        psr_rejections += sharpe.metrics["probabilistic_sharpe_ratio"] >= 0.95

    # Fixed-seed guardrails, deliberately wider than a formal Monte Carlo acceptance interval.
    assert permutation_rejections <= 7
    assert psr_rejections <= 7


def test_pbo_separates_persistent_edge_from_forced_selection_overfit() -> None:
    rng = np.random.default_rng(408)
    performance = rng.normal(size=(120, 12))
    performance -= performance.mean(axis=0)

    overfit = probability_of_backtest_overfitting(
        performance,
        partitions=6,
        statistic="mean",
    )
    performance[:, 0] += 1.0
    persistent = probability_of_backtest_overfitting(
        performance,
        partitions=6,
        statistic="mean",
    )

    assert overfit.metrics["pbo"] >= 0.9
    assert persistent.metrics["pbo"] <= 0.1
