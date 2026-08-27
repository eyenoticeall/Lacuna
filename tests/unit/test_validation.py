from __future__ import annotations

import math
from collections.abc import Mapping

import numpy as np
import polars as pl
import pytest

import lacuna as lc
from lacuna.exceptions import ConfigurationError, DataContractError, MethodContractError
from lacuna.experiment import ExperimentRegistry
from lacuna.types import AnalysisResult, JsonValue, ResultMetadata
from lacuna.validation import _bootstrap_indices, bootstrap, multiple_testing, parameter_surface


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


def test_bootstrap_honors_scoped_memory_limit_without_changing_rng_streams() -> None:
    values = np.linspace(-0.02, 0.03, 40)
    unrestricted = bootstrap(
        values,
        method="circular",
        block_length=5,
        resamples=150,
        seed=9,
        store_distribution=True,
        use_native=True,
    )
    with lc.config(memory_limit="2KiB"):
        bounded = bootstrap(
            values,
            method="circular",
            block_length=5,
            resamples=150,
            seed=9,
            store_distribution=True,
            use_native=True,
        )

    assert bounded.metadata.parameters["batch_size"] == 2
    assert bounded.metadata.parameters["native_threads"] == 1
    assert bounded.metadata.parameters["temporary_workspace_bytes"] == 640
    assert bounded.table("resample_distribution") == unrestricted.table("resample_distribution")


def test_bootstrap_rejects_memory_limit_before_fixed_output_allocation() -> None:
    with (
        lc.config(memory_limit="799B"),
        pytest.raises(ConfigurationError, match="fixed output allocation"),
    ):
        bootstrap([1.0, 2.0, 3.0], resamples=100, seed=3)


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


@pytest.mark.parametrize(
    ("method", "expected"),
    [
        ("bonferroni", [0.04, 0.16, 0.12, 0.8]),
        ("holm", [0.04, 0.09, 0.09, 0.2]),
        ("benjamini_hochberg", [0.04, 0.05333333333333334, 0.05333333333333334, 0.2]),
        (
            "benjamini_yekutieli",
            [0.08333333333333333, 0.1111111111111111, 0.1111111111111111, 0.41666666666666663],
        ),
    ],
)
def test_multiple_testing_matches_hand_computed_adjustments(
    method: str, expected: list[float]
) -> None:
    result = multiple_testing(
        [0.01, 0.04, 0.03, 0.2],
        method=method,  # type: ignore[arg-type]
    )

    observed = [row["adjusted_p_value"] for row in result.table("adjusted_p_values")]  # type: ignore[index, union-attr]
    assert observed == pytest.approx(expected)
    assert result.metrics["trial_count"] == 4


def test_multiple_testing_preserves_trial_identity_and_rank() -> None:
    frame = pl.DataFrame(
        {
            "candidate": ["slow", "fast", "medium"],
            "probability": [0.2, 0.01, 0.04],
        }
    )
    result = multiple_testing(
        frame,
        trial="candidate",
        p_value="probability",
        method="holm",
        alpha=0.05,
    )

    table = result.table("adjusted_p_values")
    assert [row["trial_id"] for row in table] == ["slow", "fast", "medium"]  # type: ignore[index, union-attr]
    assert [row["rank"] for row in table] == [3, 1, 2]  # type: ignore[index, union-attr]
    assert result.metrics["rejected_count"] == 1
    assert result.metadata.input_fingerprint is not None


def test_multiple_testing_consumes_current_complete_registry_trials() -> None:
    registry = ExperimentRegistry("p-value-study")
    registry.record(parameters={"window": 20}, metric=0.01, metric_name="p_value")
    registry.record(parameters={"window": 40}, metric=0.20, metric_name="p_value")

    result = multiple_testing(registry, method="bonferroni")

    assert result.metrics["trial_count"] == 2
    assert result.metadata.parameters["input"]["source_type"] == (  # type: ignore[index]
        "lacuna.experiment.ExperimentRegistry"
    )

    registry.record(
        parameters={"window": 60},
        status="failed",
        error_category="NumericalError",
    )
    with pytest.raises(DataContractError, match="without a current completed"):
        multiple_testing(registry)


def test_multiple_testing_validates_family_contracts() -> None:
    with pytest.raises(DataContractError, match=r"outside \[0, 1\]"):
        multiple_testing([0.1, 1.1])
    with pytest.raises(DataContractError, match="duplicate"):
        multiple_testing(pl.DataFrame({"trial_id": [1, 1], "p_value": [0.1, 0.2]}))
    with pytest.raises(DataContractError, match="null or NaN"):
        multiple_testing([0.1, float("nan")])
    with pytest.raises(MethodContractError, match="only supported for Bonferroni"):
        multiple_testing([0.1, 0.2], method="holm", effective_trials=1.5)


def test_effective_trial_count_is_explicit_bonferroni_evidence() -> None:
    result = multiple_testing(
        [0.02, 0.5, 0.8],
        method="bonferroni",
        effective_trials=1.5,
    )

    table = result.table("adjusted_p_values")
    assert table[0]["adjusted_p_value"] == pytest.approx(0.03)  # type: ignore[index]
    assert "user-supplied" in result.warnings[0]


def _surface_result(value: float) -> AnalysisResult:
    return AnalysisResult(
        metadata=ResultMetadata(method="test.surface_evaluator", input_fingerprint="input:v1"),
        metrics={"score": value},
    )


def test_parameter_surface_detects_an_isolated_interior_optimum() -> None:
    def evaluate(parameters: Mapping[str, JsonValue]) -> AnalysisResult:
        return _surface_result(10.0 if parameters["window"] == 2 else 1.0)

    result = parameter_surface(
        evaluate,
        grid={"window": [0, 1, 2, 3, 4]},
        objective="score",
        evaluator_name="strategy.score",
        sample_id="sample:evaluation",
        code_id="git:abc123",
    )

    assert result.metrics["selected_objective"] == 10.0
    assert result.metrics["plateau_width"] == 1
    assert result.metrics["neighbor_count"] == 2
    assert {finding.code for finding in result.findings} >= {
        "PARAMETER_ISOLATED_OPTIMUM",
        "PARAMETER_SELECTION_REUSE",
    }


def test_parameter_surface_reports_plateau_and_boundary_support() -> None:
    plateau = parameter_surface(
        lambda parameters: _surface_result(10.0 if parameters["window"] in {1, 2, 3} else 8.0),
        grid={"window": [0, 1, 2, 3, 4]},
        objective="score",
        evaluator_name="strategy.score",
        sample_id="sample:evaluation",
        code_id="git:abc123",
    )
    boundary = parameter_surface(
        lambda parameters: _surface_result(float(parameters["window"])),  # type: ignore[arg-type]
        grid={"window": [0, 1, 2, 3, 4]},
        objective="score",
        evaluator_name="strategy.score",
        sample_id="sample:evaluation",
        code_id="git:abc123",
    )

    assert plateau.metrics["plateau_width"] == 3
    assert "PARAMETER_LOCAL_STABILITY" in {finding.code for finding in plateau.findings}
    assert boundary.metrics["boundary_parameters"] == ("window",)
    assert "PARAMETER_BOUNDARY_OPTIMUM" in {finding.code for finding in boundary.findings}


def test_parameter_surface_preserves_failures_and_registry_lineage() -> None:
    registry = ExperimentRegistry("surface")

    def evaluate(parameters: Mapping[str, JsonValue]) -> AnalysisResult:
        if parameters["window"] == 1:
            raise RuntimeError("sensitive details must not be persisted")
        return _surface_result(float(parameters["window"]))  # type: ignore[arg-type]

    result = parameter_surface(
        evaluate,
        grid={"window": [0, 1, 2, 3]},
        objective="score",
        evaluator_name="strategy.score",
        sample_id="sample:evaluation",
        selection_sample_id="sample:selection",
        selected_parameters={"window": 2},
        code_id="git:abc123",
        registry=registry,
    )

    rows = result.table("parameter_surface")
    assert len(rows) == 4  # type: ignore[arg-type]
    assert result.metrics["failed_points"] == 1
    assert [attempt.status.value for attempt in registry.attempts()] == [
        "completed",
        "failed",
        "completed",
        "completed",
    ]
    assert registry.attempts()[1].error_category == "RuntimeError"
    assert "sensitive details" not in registry.to_result().to_json()
    assert "PARAMETER_SELECTION_SEPARATION" in {finding.code for finding in result.findings}


def test_parameter_surface_uses_manhattan_adjacency_in_multiple_dimensions() -> None:
    result = parameter_surface(
        lambda parameters: _surface_result(
            -float(parameters["fast"]) - float(parameters["slow"])  # type: ignore[arg-type]
        ),
        grid={"slow": [10, 20], "fast": [1, 2]},
        objective="score",
        evaluator_name="strategy.score",
        sample_id="sample:evaluation",
        code_id="git:abc123",
    )

    assert result.metrics["neighbor_count"] == 2
    assert result.metrics["boundary_parameters"] == ("fast", "slow")


def test_parameter_surface_records_an_all_failed_surface() -> None:
    def evaluate(_: Mapping[str, JsonValue]) -> AnalysisResult:
        raise ArithmeticError("not persisted")

    result = parameter_surface(
        evaluate,
        grid={"window": [1, 2]},
        objective="score",
        evaluator_name="strategy.score",
        sample_id="sample:evaluation",
        code_id="git:abc123",
    )

    assert result.metrics["successful_points"] == 0
    assert "PARAMETER_SURFACE_NO_VALID_POINT" in {finding.code for finding in result.findings}


def test_parameter_surface_validates_evaluator_and_grid_contracts() -> None:
    with pytest.raises(MethodContractError, match="selected_parameters"):
        parameter_surface(
            lambda _: _surface_result(1.0),
            grid={"window": [1, 2]},
            objective="score",
            evaluator_name="strategy.score",
            sample_id="sample:evaluation",
            code_id="git:abc123",
            selected_parameters={"window": 3},
        )
    with pytest.raises(MethodContractError, match="duplicate"):
        parameter_surface(
            lambda _: _surface_result(1.0),
            grid={"window": [1, 1]},
            objective="score",
            evaluator_name="strategy.score",
            sample_id="sample:evaluation",
            code_id="git:abc123",
        )
    with pytest.raises(DataContractError, match="finite numeric scalar"):
        parameter_surface(
            lambda _: AnalysisResult(
                metadata=ResultMetadata(method="test.surface"),
                metrics={"other": 1.0},
            ),
            grid={"window": [1]},
            objective="score",
            evaluator_name="strategy.score",
            sample_id="sample:evaluation",
            code_id="git:abc123",
            failure_policy="raise",
        )
