from __future__ import annotations

import math

import numpy as np
import pytest

from lacuna.exceptions import DataContractError, MethodContractError
from lacuna.validation import _bootstrap_indices, bootstrap


def test_iid_bootstrap_matches_its_deterministic_reference_indices() -> None:
    values = np.array([1.0, 2.0, 4.0, 8.0])
    result = bootstrap(
        values,
        method="iid",
        statistic="mean",
        resamples=100,
        seed=17,
        store_distribution=True,
        use_native=False,
    )
    distribution = result.table("resample_distribution")
    first_indices = _bootstrap_indices(
        size=4,
        method="iid",
        block_length=1,
        seed=17,
        replicate=0,
    )
    assert distribution[0]["statistic"] == pytest.approx(values[first_indices].mean())  # type: ignore[index]
    assert result.metrics["observed"] == pytest.approx(3.75)


@pytest.mark.parametrize("method", ["moving", "circular", "stationary"])
def test_dependent_bootstraps_are_seeded_and_reproducible(method: str) -> None:
    values = np.linspace(-0.02, 0.03, 40)
    first = bootstrap(
        values,
        method=method,  # type: ignore[arg-type]
        block_length=5,
        resamples=150,
        seed=9,
        store_distribution=True,
        batch_memory_bytes=1024,
    )
    second = bootstrap(
        values,
        method=method,  # type: ignore[arg-type]
        block_length=5,
        resamples=150,
        seed=9,
        store_distribution=True,
        batch_memory_bytes=1024 * 1024,
    )
    assert first.table("resample_distribution") == second.table("resample_distribution")
    assert first.metadata.seed == 9


def test_native_and_reference_mean_bootstrap_agree() -> None:
    values = np.linspace(-1.0, 2.0, 50)
    native = bootstrap(
        values,
        method="circular",
        block_length=7,
        resamples=200,
        seed=42,
        store_distribution=True,
        use_native=True,
    )
    reference = bootstrap(
        values,
        method="circular",
        block_length=7,
        resamples=200,
        seed=42,
        store_distribution=True,
        use_native=False,
    )
    native_values = [row["statistic"] for row in native.table("resample_distribution")]  # type: ignore[union-attr]
    reference_values = [
        row["statistic"]
        for row in reference.table("resample_distribution")  # type: ignore[union-attr]
    ]
    assert native_values == pytest.approx(reference_values, abs=1e-15)
    assert native.metadata.parameters["backend"] == "rust_native"


def test_percentile_and_basic_interval_relationship() -> None:
    values = np.arange(1.0, 11.0)
    percentile = bootstrap(values, method="iid", resamples=200, seed=4)
    basic = bootstrap(values, method="iid", resamples=200, seed=4, interval="basic")
    observed = float(percentile.metrics["observed"])
    assert basic.metrics["confidence_lower"] == pytest.approx(
        2 * observed - float(percentile.metrics["confidence_upper"])
    )
    assert basic.metrics["confidence_upper"] == pytest.approx(
        2 * observed - float(percentile.metrics["confidence_lower"])
    )


def test_stationary_restart_frequency_matches_expected_block_length() -> None:
    size = 500
    expected_length = 10
    restarts = 0
    transitions = 0
    for replicate in range(100):
        indices = _bootstrap_indices(
            size=size,
            method="stationary",
            block_length=expected_length,
            seed=123,
            replicate=replicate,
        )
        restarts += int(np.sum(indices[1:] != (indices[:-1] + 1) % size))
        transitions += size - 1
    assert restarts / transitions == pytest.approx(1 / expected_length, abs=0.015)


def test_median_and_sharpe_statistics_have_defined_behavior() -> None:
    median = bootstrap([1.0, 2.0, 100.0], statistic="median", resamples=100, seed=1)
    assert median.metrics["observed"] == 2.0
    with pytest.raises(DataContractError, match="zero-variance"):
        bootstrap([1.0, 1.0, 1.0], statistic="sharpe", resamples=100, seed=1)


def test_null_policy_and_infinity_are_distinct() -> None:
    dropped = bootstrap([1.0, None, 2.0, float("nan")], resamples=100, seed=2)
    assert dropped.metrics["n_raw"] == 2
    assert dropped.metrics["excluded_rows"] == 2
    with pytest.raises(DataContractError, match="infinity"):
        bootstrap([1.0, math.inf, 2.0], resamples=100, seed=2)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"resamples": 99}, "at least 100"),
        ({"confidence_level": 1.0}, "between zero and one"),
        ({"method": "iid", "block_length": 2}, "does not apply"),
        ({"method": "moving", "block_length": 100}, "sample size"),
        ({"method": "moving", "expected_block_length": 2}, "only valid"),
    ],
)
def test_invalid_bootstrap_configuration_is_rejected(
    kwargs: dict[str, object], message: str
) -> None:
    with pytest.raises(MethodContractError, match=message):
        bootstrap([1.0, 2.0, 3.0], seed=1, **kwargs)  # type: ignore[arg-type]


def test_bootstrap_sequence_records_copy_diagnostics() -> None:
    result = bootstrap([1.0, 2.0, 3.0], resamples=100, seed=3)
    diagnostics = result.metadata.parameters["input"]

    assert diagnostics["source_type"] == "builtins.list"  # type: ignore[index]
    assert diagnostics["adapter_copy"] == "one_copy"  # type: ignore[index]
    assert diagnostics["execution_operations"] == (  # type: ignore[index]
        "project_and_cast_float64",
    )
