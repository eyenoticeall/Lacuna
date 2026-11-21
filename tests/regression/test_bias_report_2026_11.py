"""Regression tests for lacuna.bias defects reported against v0.14.1."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import polars as pl
import pytest

from lacuna import bias
from lacuna.bias import asof_join, survivorship_diagnostics, universe_drift
from lacuna.exceptions import DataContractError, MethodContractError


def _int_frames() -> tuple[pl.DataFrame, pl.DataFrame]:
    left = pl.DataFrame({"decision_time": [10], "instrument": ["A"]})
    right = pl.DataFrame({"available_time": [8], "instrument": ["A"], "value": [1.0]})
    return left, right


def _datetime_frames(dtype: pl.DataType | None = None) -> tuple[pl.DataFrame, pl.DataFrame]:
    dtype = dtype or pl.Datetime("us", "UTC")
    left = pl.DataFrame(
        {"decision_time": [datetime(2024, 3, 10, tzinfo=UTC)], "instrument": ["A"]}
    ).with_columns(pl.col("decision_time").cast(dtype))
    right = pl.DataFrame(
        {
            "available_time": [datetime(2024, 3, 8, tzinfo=UTC)],
            "instrument": ["A"],
            "value": [1.0],
        }
    ).with_columns(pl.col("available_time").cast(dtype))
    return left, right


# --- A. tolerance must match the unit system of the time column -------------------------


@pytest.mark.parametrize("tolerance", ["30D", "1d", "1mo", timedelta(days=1), "abc"])
def test_integer_time_rejects_duration_tolerance_with_contract_error_not_panic(
    tolerance: object,
) -> None:
    left, right = _int_frames()
    with pytest.raises(MethodContractError, match="index units"):
        asof_join(left, right, tolerance=tolerance, revision_mode="not_applicable")  # type: ignore[arg-type]


def test_integer_time_rejects_fractional_tolerance() -> None:
    left, right = _int_frames()
    with pytest.raises(MethodContractError, match="whole number"):
        asof_join(left, right, tolerance=1.5, revision_mode="not_applicable")


def test_integer_time_still_accepts_whole_number_tolerance() -> None:
    left, right = _int_frames()
    kept = asof_join(left, right, tolerance=2, revision_mode="not_applicable")
    stale = asof_join(left, right, tolerance=1, revision_mode="not_applicable")
    assert kept.frame.item(0, "value") == 1.0
    assert stale.frame.item(0, "value") is None
    assert stale.evidence.metrics["stale_matches_rejected"] == 1


@pytest.mark.parametrize(
    "tolerance",
    ["30D", "1mo", "1q", "1y", "abc", "1", "-1d", "1i", "", " 1d"],
)
def test_temporal_time_rejects_unsupported_duration_strings(tolerance: str) -> None:
    left, right = _datetime_frames()
    with pytest.raises(MethodContractError):
        asof_join(left, right, tolerance=tolerance, revision_mode="not_applicable")


@pytest.mark.parametrize("tolerance", [1, 86_400_000_000, 1.0])
def test_temporal_time_rejects_unitless_numeric_tolerance(tolerance: float) -> None:
    left, right = _datetime_frames()
    with pytest.raises(MethodContractError, match="no unit"):
        asof_join(left, right, tolerance=tolerance, revision_mode="not_applicable")
    date_left = pl.DataFrame({"decision_time": [date(2024, 1, 10)], "instrument": ["A"]})
    date_right = pl.DataFrame({"available_time": [date(2024, 1, 9)], "instrument": ["A"]})
    with pytest.raises(MethodContractError, match="no unit"):
        asof_join(date_left, date_right, tolerance=tolerance, revision_mode="not_applicable")


@pytest.mark.parametrize("tolerance", ["3d", "2d1h", "72h", timedelta(days=3)])
def test_temporal_time_accepts_fixed_length_durations(tolerance: object) -> None:
    left, right = _datetime_frames()
    result = asof_join(
        left,
        right,
        tolerance=tolerance,  # type: ignore[arg-type]
        revision_mode="not_applicable",
    )
    assert result.frame.item(0, "value") == 1.0


def test_temporal_tolerance_rejects_stale_match_and_numeric_tolerance_on_duration_time() -> None:
    left, right = _datetime_frames()
    stale = asof_join(left, right, tolerance="1d", revision_mode="not_applicable")
    assert stale.frame.item(0, "value") is None
    durations_left = pl.DataFrame(
        {"decision_time": pl.Series([10], dtype=pl.Duration("us")), "instrument": ["A"]}
    )
    durations_right = pl.DataFrame(
        {"available_time": pl.Series([8], dtype=pl.Duration("us")), "instrument": ["A"]}
    )
    with pytest.raises(MethodContractError, match="no unit"):
        asof_join(durations_left, durations_right, tolerance=2, revision_mode="not_applicable")


def test_tolerance_of_unsupported_python_type_is_a_contract_error() -> None:
    left, right = _int_frames()
    with pytest.raises(MethodContractError, match="number, timedelta, or duration string"):
        asof_join(left, right, tolerance=[1], revision_mode="not_applicable")  # type: ignore[arg-type]


# --- B. effective_time is validation-only; the contract must say so ---------------------


def test_effective_time_is_validated_but_does_not_affect_matching() -> None:
    left = pl.DataFrame({"decision_time": [6], "instrument": ["A"]})
    # A late restatement of an older period (effective 1, available 5) outranks a newer
    # period's first print (effective 2, available 3): selection is by availability only.
    right = pl.DataFrame(
        {
            "available_time": [3, 5],
            "effective_time": [2, 1],
            "instrument": ["A", "A"],
            "value": [20.0, 10.0],
        }
    )
    with_effective = asof_join(
        left, right, effective_time="effective_time", revision_mode="not_applicable"
    )
    without = asof_join(left, right, revision_mode="not_applicable")

    assert with_effective.frame.item(0, "value") == without.frame.item(0, "value") == 10.0
    assert any("does not affect matching" in text for text in with_effective.evidence.warnings)
    assert not any("effective_time" in text for text in without.evidence.warnings)
    bad = right.with_columns(pl.col("effective_time").cast(pl.String))
    with pytest.raises(DataContractError, match="effective_time"):
        asof_join(left, bad, effective_time="effective_time", revision_mode="not_applicable")


# --- C. future_matches is computed evidence, not a constant ------------------------------


def test_future_match_count_detects_a_planted_future_record() -> None:
    frame = pl.DataFrame(
        {"decision_time": [1, 2, 3, 4], "matched": pl.Series([1, 3, None, 4], dtype=pl.Int64)}
    )
    assert bias._future_match_count(frame, left_time="decision_time", matched_time="matched") == 1


def test_asof_join_fails_closed_when_the_future_match_check_is_nonzero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    left, right = _int_frames()
    monkeypatch.setattr(bias, "_future_match_count", lambda *_args, **_kwargs: 2)
    with pytest.raises(RuntimeError, match="future data for 2 decision rows"):
        asof_join(left, right, revision_mode="not_applicable")


def test_future_matches_metric_is_an_integer_invariant_check() -> None:
    left, right = _int_frames()
    metrics = asof_join(left, right, revision_mode="not_applicable").evidence.metrics
    assert metrics["future_matches"] == 0
    assert isinstance(metrics["future_matches"], int)


# --- D. revision ties need a declared version order --------------------------------------


@pytest.mark.parametrize("dtype", [pl.String, pl.Categorical])
def test_lexicographic_revision_dtypes_are_rejected_because_10_would_rank_below_9(
    dtype: pl.DataType,
) -> None:
    left = pl.DataFrame({"decision_time": [5], "instrument": ["A"]})
    right = pl.DataFrame(
        {
            "available_time": [1, 1],
            "instrument": ["A", "A"],
            "revision_id": pl.Series(["9", "10"]).cast(dtype),
        }
    )
    with pytest.raises(DataContractError, match="no declared version order"):
        asof_join(left, right, revision="revision_id", revision_mode="point_in_time")


def test_enum_revision_uses_declared_category_order() -> None:
    left = pl.DataFrame({"decision_time": [5], "instrument": ["A"]})
    right = pl.DataFrame(
        {
            "available_time": [1, 1],
            "instrument": ["A", "A"],
            "revision_id": pl.Series(["10", "9"], dtype=pl.Enum(["9", "10"])),
            "value": [10.0, 9.0],
        }
    )
    result = asof_join(left, right, revision="revision_id", revision_mode="point_in_time")
    assert result.frame.item(0, "value") == 10.0


def test_integer_revision_ties_pick_greatest_revision_numerically() -> None:
    left = pl.DataFrame({"decision_time": [5], "instrument": ["A"]})
    right = pl.DataFrame(
        {
            "available_time": [1, 1],
            "instrument": ["A", "A"],
            "revision_id": [9, 10],
            "value": [9.0, 10.0],
        }
    )
    result = asof_join(left, right, revision="revision_id", revision_mode="point_in_time")
    assert result.frame.item(0, "value") == 10.0


def test_non_finite_float_revision_is_rejected() -> None:
    left = pl.DataFrame({"decision_time": [5], "instrument": ["A"]})
    right = pl.DataFrame(
        {
            "available_time": [1, 1],
            "instrument": ["A", "A"],
            "revision_id": [1.0, float("nan")],
        }
    )
    with pytest.raises(DataContractError, match="finite"):
        asof_join(left, right, revision="revision_id", revision_mode="point_in_time")


def test_revision_dtype_contract_does_not_depend_on_whether_ties_exist() -> None:
    left = pl.DataFrame({"decision_time": [5], "instrument": ["A"]})
    right = pl.DataFrame({"available_time": [1], "instrument": ["A"], "revision_id": ["only-one"]})
    with pytest.raises(DataContractError, match="no declared version order"):
        asof_join(left, right, revision="revision_id", revision_mode="point_in_time")


# --- E. survivorship and drift must not PASS on evidence that cannot establish safety ----


def _membership(delisted: list[bool | None]) -> pl.DataFrame:
    count = len(delisted)
    return pl.DataFrame(
        {
            "index": ["LAC"] * count,
            "instrument": [f"I{i}" for i in range(count)],
            "valid_from": [1] * count,
            "valid_to": pl.Series([None] * count, dtype=pl.Int64),
            "available_time": [1] * count,
            "delisted": pl.Series(delisted, dtype=pl.Boolean),
        }
    )


@pytest.mark.parametrize("delisted", [[False, False], [None, None]])
def test_confirmed_safe_without_any_observed_delisting_is_unknown_not_pass(
    delisted: list[bool | None],
) -> None:
    result = survivorship_diagnostics(
        _membership(delisted),
        delisted="delisted",
        source_status="confirmed_safe",
        includes_delisted=True,
    )
    states = {finding.code: finding.state.value for finding in result.findings}

    assert states == {"BIAS_SURVIVORSHIP_DELISTINGS_NOT_OBSERVED": "UNKNOWN"}
    assert result.metrics["delisted_rows"] == 0
    assert result.metadata.method_version == 2


def test_confirmed_safe_with_an_observed_delisting_still_passes() -> None:
    result = survivorship_diagnostics(
        _membership([True, False]),
        delisted="delisted",
        source_status="confirmed_safe",
        includes_delisted=True,
    )
    assert {finding.code for finding in result.findings} == {"BIAS_SURVIVORSHIP_SAFE"}


def test_single_snapshot_universe_drift_is_unknown_with_null_drift_not_pass() -> None:
    frame = pl.DataFrame({"snapshot_time": [1, 1], "instrument": ["A", "B"]})
    result = universe_drift(frame, source_status="confirmed_safe")
    states = {finding.code: finding.state.value for finding in result.findings}

    assert states == {"BIAS_UNIVERSE_DRIFT_UNDEFINED": "UNKNOWN"}
    assert result.metrics["transitions"] == 0
    assert result.metrics["mean_drift"] is None
    assert result.metrics["maximum_drift"] is None
    assert result.metadata.method_version == 2
    json.loads(result.to_json())  # finite, strict JSON with null rather than NaN


def test_single_snapshot_drift_is_reported_even_when_source_status_is_unknown() -> None:
    frame = pl.DataFrame({"snapshot_time": [1], "instrument": ["A"]})
    result = universe_drift(frame)
    assert {finding.code for finding in result.findings} == {
        "BIAS_UNIVERSE_DRIFT_UNDEFINED",
        "BIAS_SURVIVORSHIP_UNKNOWN",
    }


def test_one_universe_with_a_single_snapshot_is_not_hidden_by_another_universes_transitions() -> (
    None
):
    frame = pl.DataFrame(
        {
            "universe": ["u1", "u1", "u2"],
            "snapshot_time": [1, 2, 1],
            "instrument": ["A", "A", "B"],
        }
    )
    result = universe_drift(frame, universe="universe", source_status="confirmed_safe")
    undefined = [f for f in result.findings if f.code == "BIAS_UNIVERSE_DRIFT_UNDEFINED"]

    assert result.metrics["transitions"] == 1
    assert result.metrics["universes_without_transitions"] == 1
    assert len(undefined) == 1
    assert undefined[0].state.value == "UNKNOWN"
    assert not any(f.state.value == "PASS" for f in result.findings)


def test_multi_snapshot_confirmed_safe_universe_drift_still_passes() -> None:
    frame = pl.DataFrame({"snapshot_time": [1, 1, 2, 2], "instrument": ["A", "B", "A", "B"]})
    result = universe_drift(frame, source_status="confirmed_safe")
    assert {finding.code for finding in result.findings} == {"BIAS_UNIVERSE_DRIFT_MEASURED"}
    assert result.metrics["mean_drift"] == 0.0
