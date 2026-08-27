from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np
import polars as pl
import pytest

import lacuna as lc
from lacuna.exceptions import DataContractError, MethodContractError
from lacuna.validation import (
    joint_stationary_bootstrap,
    permutation_test,
    probability_of_backtest_overfitting,
    reality_check,
    sharpe_inference,
    superior_predictive_ability,
)


def test_sign_flip_permutation_matches_deterministic_reference_streams() -> None:
    values = np.asarray([1.0, 2.0, 3.0, 4.0])
    result = permutation_test(
        values,
        scheme="sign_flip",
        statistic="mean",
        permutations=100,
        alternative="greater",
        seed=7,
        store_distribution=True,
    )
    expected = []
    for replicate in range(100):
        rng = np.random.default_rng(np.random.SeedSequence([7, 2, replicate]))
        signs = rng.choice(np.asarray([-1.0, 1.0]), size=values.size)
        expected.append(float(np.mean(values * signs)))

    observed = [row["statistic"] for row in result.table("permutation_distribution")]
    assert observed == expected
    exceedances = sum(value >= values.mean() for value in expected)
    assert result.metrics["p_value"] == (exceedances + 1) / 101


def test_unrestricted_permutation_detects_strong_pairwise_association() -> None:
    values = np.arange(20, dtype=np.float64)
    frame = pl.DataFrame({"signal": values, "outcome": values * 3.0 + 2.0})
    result = permutation_test(
        frame,
        value="signal",
        paired_with="outcome",
        statistic="pearson",
        scheme="unrestricted",
        permutations=499,
        seed=11,
    )

    assert result.metrics["observed"] == pytest.approx(1.0)
    assert result.metrics["p_value"] <= 0.01


def test_stratified_and_block_permutation_contracts_are_explicit() -> None:
    frame = pl.DataFrame(
        {
            "time": [0, 0, 1, 1],
            "signal": [1.0, 2.0, 3.0, 4.0],
            "outcome": [4.0, 3.0, 2.0, 1.0],
        }
    )
    result = permutation_test(
        frame,
        value="signal",
        paired_with="outcome",
        statistic="pearson",
        scheme="within_date",
        permutations=100,
        seed=3,
    )
    assert result.metadata.parameters["stratum_column"] == "time"

    with pytest.raises(MethodContractError, match="paired_with"):
        permutation_test([1.0, 2.0, 3.0], scheme="unrestricted", permutations=100)
    with pytest.raises(MethodContractError, match="invariant to reordering"):
        permutation_test(
            frame,
            value="signal",
            paired_with="outcome",
            scheme="unrestricted",
            permutations=100,
        )
    with pytest.raises(MethodContractError, match="block_length"):
        permutation_test(
            frame,
            value="signal",
            paired_with="outcome",
            statistic="pearson",
            scheme="block",
            permutations=100,
        )


def test_sharpe_inference_matches_the_published_moment_equations() -> None:
    values = np.asarray([-0.01, 0.02, 0.03, -0.005, 0.015, 0.01, 0.025, -0.002])
    result = sharpe_inference(
        values,
        benchmark=0.1,
        annualization=12.0,
        confidence_level=0.95,
    )

    mean = float(values.mean())
    standard_deviation = float(values.std(ddof=1))
    centered = values - mean
    population_scale = float(np.sqrt(np.mean(centered**2)))
    skewness = float(np.mean(centered**3) / population_scale**3)
    kurtosis = float(np.mean(centered**4) / population_scale**4)
    periodic_sharpe = mean / standard_deviation
    variance_factor = 1.0 - skewness * periodic_sharpe + (kurtosis - 1.0) * periodic_sharpe**2 / 4.0
    periodic_se = math.sqrt(variance_factor / (values.size - 1))
    expected_psr = NormalDist().cdf((periodic_sharpe - 0.1 / math.sqrt(12.0)) / periodic_se)

    assert result.metrics["observed_sharpe"] == pytest.approx(periodic_sharpe * math.sqrt(12.0))
    assert result.metrics["standard_error"] == pytest.approx(periodic_se * math.sqrt(12.0))
    assert result.metrics["probabilistic_sharpe_ratio"] == pytest.approx(expected_psr)
    interval_z = NormalDist().inv_cdf(0.975)
    assert result.metrics["confidence_lower"] == pytest.approx(
        result.metrics["observed_sharpe"] - interval_z * result.metrics["standard_error"]
    )
    assert result.metrics["confidence_upper"] == pytest.approx(
        result.metrics["observed_sharpe"] + interval_z * result.metrics["standard_error"]
    )


def test_deflated_sharpe_uses_and_exposes_the_complete_trial_family() -> None:
    values = np.linspace(-0.01, 0.03, 80) + np.sin(np.arange(80)) * 0.01
    selected_sharpe = float(values.mean() / values.std(ddof=1) * math.sqrt(12.0))
    trials = [0.1, 0.2, 0.3, 0.4, selected_sharpe]
    result = sharpe_inference(
        values,
        annualization=12.0,
        trial_sharpes=trials,
        independent_trials=4.0,
    )

    assert result.metrics["trial_count"] == 5
    assert result.metrics["trial_sharpe_mean"] == pytest.approx(np.mean(trials))
    assert result.metrics["trial_sharpe_standard_deviation"] == pytest.approx(
        np.std(trials, ddof=1)
    )
    assert result.metrics["deflated_sharpe_threshold"] is not None
    assert result.metrics["deflated_sharpe_ratio"] <= result.metrics["probabilistic_sharpe_ratio"]
    assert [row["sharpe"] for row in result.table("trial_sharpes")] == pytest.approx(trials)


def test_sharpe_inference_rejects_undefined_or_incomplete_inputs() -> None:
    with pytest.raises(DataContractError, match="zero-variance"):
        sharpe_inference([1.0, 1.0, 1.0])
    with pytest.raises(MethodContractError, match="complete trial_sharpes"):
        sharpe_inference([1.0, 2.0, 3.0], independent_trials=2.0)
    with pytest.raises(DataContractError, match="selected strategy"):
        sharpe_inference(
            [-1.0, 0.0, 2.0, 3.0],
            trial_sharpes=[0.1, 0.2],
        )


def test_pbo_exposes_selection_rank_logit_and_partition_sensitivity() -> None:
    base = np.asarray([-0.4, 0.1, -0.2, 0.3, -0.1, 0.4, -0.3, 0.2])
    matrix = np.column_stack((base + 2.0, base + 1.0, base))
    result = probability_of_backtest_overfitting(
        matrix,
        partitions=4,
        partition_sensitivity=[2],
    )

    assert result.metrics["n_combinations"] == 6
    assert result.metrics["pbo"] == 0.0
    assert len(result.table("combinations")) == 6
    assert {row["selected_strategy"] for row in result.table("combinations")} == {"strategy_0"}
    assert all(row["relative_rank"] == 0.75 for row in result.table("combinations"))
    assert [row["partitions"] for row in result.table("partition_sensitivity")] == [4, 2]


def test_pbo_refuses_ambiguous_selection_and_unequal_partitions() -> None:
    matrix = np.column_stack((np.arange(8, dtype=float), np.arange(8, dtype=float)))
    with pytest.raises(DataContractError, match="selection has a tie"):
        probability_of_backtest_overfitting(matrix, partitions=4, statistic="mean")
    with pytest.raises(DataContractError, match="row count must divide"):
        probability_of_backtest_overfitting(np.arange(30, dtype=float).reshape(10, 3), partitions=4)
    with pytest.raises(MethodContractError, match="must be an integer"):
        probability_of_backtest_overfitting(
            np.arange(24, dtype=float).reshape(8, 3),
            partitions=4.0,  # type: ignore[arg-type]
        )


def test_joint_stationary_bootstrap_preserves_cross_strategy_structure() -> None:
    first = np.sin(np.arange(30, dtype=np.float64))
    matrix = np.column_stack((first, 2.0 * first + 3.0))
    result = joint_stationary_bootstrap(
        matrix,
        expected_block_length=4,
        resamples=100,
        seed=19,
        store_distribution=True,
    )
    rows = result.table("bootstrap_distribution")
    for replicate in range(100):
        first_mean = rows[replicate * 2]["mean"]
        second_mean = rows[replicate * 2 + 1]["mean"]
        assert second_mean == pytest.approx(2.0 * first_mean + 3.0)
    assert result.metadata.parameters["joint_indices"] is True


def test_joint_bootstrap_batch_budget_preserves_rng_and_distribution() -> None:
    first = np.sin(np.arange(30, dtype=np.float64))
    matrix = np.column_stack((first, 2.0 * first + 3.0))
    unrestricted = joint_stationary_bootstrap(
        matrix,
        expected_block_length=4,
        resamples=100,
        seed=19,
        store_distribution=True,
    )
    with lc.config(memory_limit="3KiB"):
        bounded = joint_stationary_bootstrap(
            matrix,
            expected_block_length=4,
            resamples=100,
            seed=19,
            store_distribution=True,
        )

    assert bounded.table("bootstrap_distribution") == unrestricted.table("bootstrap_distribution")


def test_reality_check_handles_no_edge_and_detects_a_clear_edge() -> None:
    rng = np.random.default_rng(22)
    no_edge = -1.0 + rng.normal(scale=0.1, size=(80, 3))
    negative = reality_check(
        no_edge,
        expected_block_length=5,
        resamples=199,
        seed=2,
    )
    assert negative.metrics["statistic"] == 0.0
    assert negative.metrics["p_value"] == 1.0

    edge = rng.normal(scale=0.2, size=(80, 3))
    edge[:, 0] += 0.8
    positive = reality_check(
        edge,
        expected_block_length=5,
        resamples=499,
        seed=2,
    )
    assert positive.metrics["best_strategy"] == "strategy_0"
    assert positive.metrics["p_value"] <= 0.01


def test_spa_exposes_ordered_recenterings_and_detects_a_clear_edge() -> None:
    rng = np.random.default_rng(71)
    matrix = rng.normal(scale=0.2, size=(100, 5))
    matrix[:, 0] += 0.7
    matrix[:, 3:] -= 0.5
    result = superior_predictive_ability(
        matrix,
        expected_block_length=6,
        resamples=499,
        seed=5,
        store_distribution=True,
    )

    assert result.metrics["best_strategy"] == "strategy_0"
    assert result.metrics["p_value_lower"] <= result.metrics["p_value_consistent"]
    assert result.metrics["p_value_consistent"] <= result.metrics["p_value_upper"]
    assert result.metrics["p_value_consistent"] <= 0.01
    assert [row["recentering"] for row in result.table("p_values")] == [
        "lower",
        "consistent",
        "upper",
    ]


def test_spa_rejects_a_strategy_without_studentization_variance() -> None:
    matrix = np.column_stack((np.ones(20), np.arange(20, dtype=np.float64)))
    with pytest.raises(DataContractError, match="long-run variance"):
        superior_predictive_ability(matrix, resamples=100, seed=1)
