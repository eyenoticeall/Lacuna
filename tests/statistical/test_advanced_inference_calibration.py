from __future__ import annotations

import numpy as np

from lacuna.validation import (
    permutation_test,
    probability_of_backtest_overfitting,
    reality_check,
    sharpe_inference,
    superior_predictive_ability,
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


def test_reality_check_and_spa_have_reasonable_fixed_seed_null_size_and_power() -> None:
    rng = np.random.default_rng(991)
    reality_rejections = 0
    spa_rejections = 0
    simulations = 30
    for simulation in range(simulations):
        matrix = rng.normal(size=(80, 5))
        reality = reality_check(
            matrix,
            expected_block_length=1,
            resamples=199,
            seed=simulation,
        )
        spa = superior_predictive_ability(
            matrix,
            expected_block_length=1,
            resamples=199,
            seed=simulation,
        )
        reality_rejections += reality.metrics["p_value"] <= 0.05
        spa_rejections += spa.metrics["p_value_consistent"] <= 0.05

    assert reality_rejections <= 5
    assert spa_rejections <= 5

    edge = rng.normal(size=(100, 8))
    edge[:, 0] += 0.8
    reality = reality_check(edge, expected_block_length=3, resamples=499, seed=4)
    spa = superior_predictive_ability(
        edge,
        expected_block_length=3,
        resamples=499,
        seed=4,
    )
    assert reality.metrics["p_value"] <= 0.01
    assert spa.metrics["p_value_consistent"] <= 0.01


def test_spa_is_not_diluted_by_irrelevant_poor_high_variance_models() -> None:
    rng = np.random.default_rng(772)
    base = rng.normal(scale=0.4, size=(120, 2))
    base[:, 0] += 0.25
    poor = np.column_stack(
        (base, rng.normal(loc=-5.0, scale=10.0, size=(120, 30)))
    )

    reality = reality_check(poor, expected_block_length=3, resamples=499, seed=9)
    spa = superior_predictive_ability(
        poor,
        expected_block_length=3,
        resamples=499,
        seed=9,
    )

    assert reality.metrics["p_value"] >= 0.5
    assert spa.metrics["p_value_consistent"] <= 0.01
