"""Regression tests for cross-validation and validation defects reported against v0.14.1."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timedelta

import numpy as np
import polars as pl
import pytest

from lacuna.cv import CombinatorialPurgedKFold, PurgedKFold, WalkForward
from lacuna.exceptions import DataContractError, MethodContractError
from lacuna.experiment import ExperimentRegistry
from lacuna.types import AnalysisResult, JsonValue, ResultMetadata
from lacuna.validation import bootstrap, multiple_testing, parameter_surface

# --- 1. PurgedKFold embargo/n_splits type validation ---------------------------------------


@pytest.mark.parametrize("embargo", ["5D", 1.5, 0.0, True])
def test_purged_kfold_rejects_non_integer_embargo_at_construction_like_cpcv(
    embargo: object,
) -> None:
    with pytest.raises(MethodContractError, match="invalid types: embargo"):
        PurgedKFold(embargo=embargo)  # type: ignore[arg-type]
    with pytest.raises(MethodContractError, match="invalid types: embargo"):
        CombinatorialPurgedKFold(embargo=embargo)  # type: ignore[arg-type]


@pytest.mark.parametrize("n_splits", [2.0, "3", True])
def test_purged_kfold_rejects_non_integer_n_splits_at_construction(n_splits: object) -> None:
    with pytest.raises(MethodContractError, match="invalid types: n_splits"):
        PurgedKFold(n_splits=n_splits)  # type: ignore[arg-type]


def test_purged_kfold_still_accepts_integer_embargo() -> None:
    assert PurgedKFold(n_splits=3, embargo=2).embargo == 2
    with pytest.raises(MethodContractError, match="non-negative"):
        PurgedKFold(embargo=-1)


# --- 2. Calendar walk-forward keeps a window ending one day past the last Date -----------


def _daily(periods: int, *, as_datetime: bool = False) -> pl.DataFrame:
    origin = datetime(2025, 1, 1) if as_datetime else date(2025, 1, 1)
    return pl.DataFrame({"time": [origin + timedelta(days=day) for day in range(periods)]})


def test_calendar_walk_forward_keeps_window_whose_exclusive_end_is_one_day_past_last_date() -> None:
    # 10 daily Dates; train 5D / test 5D / step 5D gives one window [Jan 6, Jan 11) whose
    # exclusive end is exactly last (Jan 10) + 1 day. It is fully covered by data and must
    # match the integer-mode result, which keeps the window ending at the last observation.
    frame = _daily(10)
    calendar_folds = WalkForward(train="5D", test="5D", step="5D").split(frame).folds
    integer_folds = WalkForward(train=5, test=5, step=5).split(frame).folds
    assert len(calendar_folds) == 1
    assert calendar_folds == integer_folds
    assert calendar_folds[0].test_indices == (5, 6, 7, 8, 9)


def test_calendar_walk_forward_matches_integer_mode_on_contiguous_daily_dates() -> None:
    frame = _daily(14)
    calendar = WalkForward(train="4D", test="2D", step="2D", mode="rolling").split(frame)
    integer = WalkForward(train=4, test=2, step=2, mode="rolling").split(frame)
    assert calendar.folds == integer.folds
    # The last observation (row 13) is tested.
    assert 13 in calendar.folds[-1].test_indices


def test_calendar_walk_forward_still_drops_window_extending_two_days_past_last_date() -> None:
    # 9 daily Dates (Jan 1..9): window [Jan 6, Jan 11) ends two days past the last Date and
    # genuinely extends beyond the data; it must stay dropped without allow_incomplete.
    frame = _daily(9)
    with pytest.raises(DataContractError, match="no complete folds"):
        WalkForward(train="5D", test="5D", step="5D").split(frame)
    incomplete = WalkForward(train="5D", test="5D", step="5D", allow_incomplete=True).split(frame)
    assert incomplete.folds[0].test_indices == (5, 6, 7, 8)


def test_calendar_walk_forward_datetime_window_past_last_instant_stays_incomplete() -> None:
    # A Datetime is an instant with no implied bar length, so coverage is never inferred:
    # the window [Jan 6, Jan 11) ends after the last instant (Jan 10 00:00) and is dropped.
    frame = _daily(10, as_datetime=True)
    with pytest.raises(DataContractError, match="no complete folds"):
        WalkForward(train="5D", test="5D", step="5D").split(frame)
    # A window ending at or before the last instant is still complete.
    folds = WalkForward(train="5D", test="4D", step="5D").split(frame).folds
    assert len(folds) == 1
    assert folds[0].test_indices == (5, 6, 7, 8)


def test_walk_forward_method_version_records_the_calendar_coverage_rule() -> None:
    result = WalkForward(train="5D", test="5D", step="5D").split(_daily(10))
    assert result.evidence.metadata.method == "cv.walk_forward"
    assert result.evidence.metadata.method_version == 2
    # Purged K-fold fold semantics are unchanged.
    intervals = pl.DataFrame(
        {
            "observation_time": list(range(6)),
            "label_start": list(range(6)),
            "label_end": [value + 2 for value in range(6)],
        }
    )
    assert PurgedKFold(n_splits=2).split(intervals).evidence.metadata.method_version == 1


# --- 3. bootstrap expected_block_length=0 --------------------------------------------------


@pytest.mark.parametrize("bad", [0, -3])
def test_bootstrap_rejects_non_positive_expected_block_length_instead_of_using_default(
    bad: int,
) -> None:
    values = np.arange(1.0, 41.0)
    with pytest.raises(MethodContractError, match="expected_block_length must be between 1"):
        bootstrap(values, method="stationary", expected_block_length=bad, resamples=100, seed=1)


def test_bootstrap_expected_block_length_validation_precedes_data_materialization() -> None:
    with pytest.raises(MethodContractError, match="expected_block_length must be between 1"):
        bootstrap(object(), method="stationary", expected_block_length=0)


def test_bootstrap_expected_block_length_must_be_an_integer() -> None:
    with pytest.raises(MethodContractError, match="expected_block_length must be an integer"):
        bootstrap(
            np.arange(1.0, 41.0),
            method="stationary",
            expected_block_length=True,  # type: ignore[arg-type]
            resamples=100,
            seed=1,
        )


def test_bootstrap_positive_expected_block_length_and_default_are_unchanged() -> None:
    values = np.arange(1.0, 41.0)
    explicit = bootstrap(
        values, method="stationary", expected_block_length=4, resamples=100, seed=1
    )
    default = bootstrap(values, method="stationary", resamples=100, seed=1)
    assert explicit.metadata.parameters["block_length"] == 4
    assert default.metadata.parameters["block_length"] == max(2, round(40 ** (1.0 / 3.0)))


# --- 4. multiple_testing registry input gets the array path's validation -------------------


def _p_value_registry(*values: float) -> ExperimentRegistry:
    registry = ExperimentRegistry("p-values")
    for index, value in enumerate(values):
        registry.record(parameters={"window": index}, metric=value, metric_name="p_value")
    return registry


@pytest.mark.parametrize("bad", [1.5, -0.1])
def test_multiple_testing_registry_rejects_p_values_outside_unit_interval(bad: float) -> None:
    registry = _p_value_registry(0.01, bad)
    with pytest.raises(DataContractError, match=r"outside \[0, 1\]"):
        multiple_testing(registry)
    # Same contract as the array path.
    with pytest.raises(DataContractError, match=r"outside \[0, 1\]"):
        multiple_testing([0.01, bad])


def test_multiple_testing_registry_accepts_boundary_p_values_and_records_null_policy() -> None:
    result = multiple_testing(_p_value_registry(0.0, 0.5, 1.0), null_policy="drop")
    assert result.metrics["trial_count"] == 3
    assert result.metrics["excluded_rows"] == 0
    assert result.metadata.parameters["null_policy"] == "drop"


def test_multiple_testing_registry_rejects_invalid_null_policy_like_array_path() -> None:
    with pytest.raises(MethodContractError, match="null_policy"):
        multiple_testing(_p_value_registry(0.1, 0.2), null_policy="ignore")  # type: ignore[arg-type]
    with pytest.raises(MethodContractError, match="null_policy"):
        multiple_testing([0.1, 0.2], null_policy="ignore")  # type: ignore[arg-type]


def test_multiple_testing_registry_still_rejects_trials_without_completed_metric() -> None:
    # A missing trial is a family-completeness error; dropping it would shrink the family
    # and understate multiplicity, so null_policy="drop" must not apply to it.
    registry = _p_value_registry(0.01, 0.2)
    registry.record(parameters={"window": 9}, status="failed", error_category="NumericalError")
    with pytest.raises(DataContractError, match="without a current completed"):
        multiple_testing(registry, null_policy="drop")


# --- 5. parameter_surface never silently discards selection_sample_id ----------------------


def _surface_result(value: float) -> AnalysisResult:
    return AnalysisResult(
        metadata=ResultMetadata(method="test.surface", method_version=1, parameters={}),
        metrics={"score": value},
    )


def _surface(**overrides: object) -> AnalysisResult:
    def evaluate(parameters: Mapping[str, JsonValue]) -> AnalysisResult:
        return _surface_result(float(parameters["window"]))  # type: ignore[arg-type]

    arguments: dict[str, object] = {
        "grid": {"window": [1, 2, 3]},
        "objective": "score",
        "evaluator_name": "strategy.score",
        "sample_id": "sample:evaluation",
        "code_id": "git:abc123",
    }
    arguments.update(overrides)
    return parameter_surface(evaluate, **arguments)  # type: ignore[arg-type]


def test_parameter_surface_rejects_distinct_selection_sample_without_selected_parameters() -> None:
    registry = ExperimentRegistry("surface")
    with pytest.raises(MethodContractError, match="selection_sample_id"):
        _surface(selection_sample_id="sample:training", registry=registry)
    # Rejected before any evaluation touches the registry.
    assert registry.attempts() == ()


def test_parameter_surface_honours_selection_sample_with_selected_parameters() -> None:
    result = _surface(selection_sample_id="sample:training", selected_parameters={"window": 2})
    assert result.metadata.parameters["selection_sample_id"] == "sample:training"
    codes = {finding.code for finding in result.findings}
    assert "PARAMETER_SELECTION_SEPARATION" in codes
    assert "PARAMETER_SELECTION_REUSE" not in codes


def test_parameter_surface_self_selection_reports_reuse_and_allows_matching_sample_id() -> None:
    plain = _surface()
    matching = _surface(selection_sample_id="sample:evaluation")
    for result in (plain, matching):
        assert result.metadata.parameters["selection_sample_id"] == "sample:evaluation"
        assert "PARAMETER_SELECTION_REUSE" in {finding.code for finding in result.findings}


def test_parameter_surface_selected_parameters_without_selection_sample_is_unknown() -> None:
    result = _surface(selected_parameters={"window": 2})
    assert "PARAMETER_SELECTION_SAMPLE_UNKNOWN" in {finding.code for finding in result.findings}


@pytest.mark.parametrize("bad", ["", " sample:training"])
def test_parameter_surface_rejects_malformed_selection_sample_id(bad: str) -> None:
    with pytest.raises(MethodContractError, match="selection_sample_id"):
        _surface(selection_sample_id=bad, selected_parameters={"window": 2})
