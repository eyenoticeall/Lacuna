"""Regression tests for the 2026-11 regime and signal-transform review findings."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl
import pytest

from lacuna.regime import quantile_regimes, regime_analysis
from lacuna.signal import neutralize
from lacuna.types import AnalysisResult, FindingState


def _state(result: AnalysisResult, code: str) -> FindingState | None:
    states = [finding.state for finding in result.findings if finding.code == code]
    assert len(states) <= 1
    return states[0] if states else None


def _codes(result: AnalysisResult) -> set[str]:
    return {finding.code for finding in result.findings}


# --- Item 1: quantile_regimes availability honesty -------------------------------------------


@pytest.mark.parametrize("method", ("fixed", "expanding", "rolling"))
def test_quantile_regimes_without_available_time_never_passes_source_availability(
    method: str,
) -> None:
    kwargs: dict[str, object] = {"method": method, "min_history": 2}
    if method == "fixed":
        kwargs.update(lower_threshold=1.5, upper_threshold=3.5)
    if method == "rolling":
        kwargs.update(window=3)
    result = quantile_regimes(
        pl.DataFrame({"time": range(5), "value": [1.0, 2.0, 3.0, 4.0, 5.0]}),
        **kwargs,  # type: ignore[arg-type]
    )

    assert _state(result, "REGIME_SOURCE_AVAILABILITY_UNKNOWN") is FindingState.UNKNOWN
    assert "REGIME_SOURCE_AVAILABLE" not in _codes(result)
    # The narrower threshold-only claim stays distinct and does not mention availability as proven.
    assert _state(result, "REGIME_THRESHOLDS_POINT_IN_TIME") is FindingState.PASS
    assert result.metadata.method_version == 2


def test_quantile_regimes_fixed_with_verified_available_time_passes_availability() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    frame = pl.DataFrame(
        {
            "time": [start, start + timedelta(days=1)],
            "available": [start, start + timedelta(days=1)],
            "value": [1.0, 2.0],
        }
    )
    result = quantile_regimes(
        frame,
        method="fixed",
        lower_threshold=0.5,
        upper_threshold=1.5,
        available_time="available",
    )

    assert _state(result, "REGIME_SOURCE_AVAILABLE") is FindingState.PASS
    assert "REGIME_SOURCE_AVAILABILITY_UNKNOWN" not in _codes(result)


def test_quantile_regimes_fixed_future_availability_still_fails() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    result = quantile_regimes(
        pl.DataFrame(
            {
                "time": [start],
                "available": [start + timedelta(days=1)],
                "value": [1.0],
            }
        ),
        method="fixed",
        lower_threshold=0.5,
        upper_threshold=1.5,
        available_time="available",
    )

    assert _state(result, "REGIME_SOURCE_NOT_AVAILABLE") is FindingState.FAIL
    assert "REGIME_SOURCE_AVAILABLE" not in _codes(result)


# --- Item 2: regime_analysis mode is an unverifiable declaration -----------------------------


def _labelled(mode_available: bool) -> pl.DataFrame:
    frame = pl.DataFrame(
        {
            "time": range(4),
            "regime": ["low", "high", "low", "high"],
            "outcome": [0.1, 0.2, -0.1, 0.3],
        }
    )
    return frame.with_columns(pl.col("time").alias("available")) if mode_available else frame


def test_regime_analysis_point_in_time_mode_is_reported_as_declaration_only() -> None:
    result = regime_analysis(
        _labelled(mode_available=True),
        classification_mode="point_in_time",
        available_time="available",
        min_observations=1,
    )

    # The limit applies to every point-in-time call, so it is a warning and a recorded
    # parameter, not an always-on UNKNOWN finding.
    assert any("caller declaration" in warning for warning in result.warnings)
    assert result.metadata.parameters["classification_provenance"] == "declared_unverified"
    assert _state(result, "REGIME_AVAILABILITY_POINT_IN_TIME") is FindingState.PASS


def test_regime_analysis_retrospective_mode_needs_no_declaration_warning() -> None:
    result = regime_analysis(
        _labelled(mode_available=False),
        classification_mode="retrospective",
        min_observations=1,
    )

    assert not any("caller declaration" in warning for warning in result.warnings)
    assert result.metadata.parameters["classification_provenance"] == "declared_unverified"


# --- Item 3: neutralize availability finding names the inputs it concerns --------------------


def _panel() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "time": [0] * 4,
            "instrument": ["i1", "i2", "i3", "i4"],
            "signal": [1.0, 3.0, 10.0, 14.0],
            "sector": ["a", "a", "b", "b"],
        }
    )


def test_neutralize_unknown_availability_finding_names_exposure_inputs() -> None:
    # Exposures are always externally supplied attributes, so UNKNOWN (never PASS or omission)
    # remains correct under default by=time, but it must say which inputs it is about.
    result = neutralize(_panel(), exposures=("sector",), categorical=("sector",)).evidence

    assert _state(result, "GROUP_AVAILABILITY_UNKNOWN") is FindingState.UNKNOWN
    finding = next(f for f in result.findings if f.code == "GROUP_AVAILABILITY_UNKNOWN")
    assert finding.evidence["exposure_columns"] == ("sector",)
    assert finding.evidence["group_columns"] == ()
    assert "sector" in finding.message


def test_neutralize_unknown_availability_names_group_columns_when_grouped() -> None:
    frame = _panel().with_columns(pl.lit("x").alias("book"), pl.col("signal").alias("beta"))
    result = neutralize(frame, exposures=("beta",), by=("time", "book")).evidence

    finding = next(f for f in result.findings if f.code == "GROUP_AVAILABILITY_UNKNOWN")
    assert finding.evidence["group_columns"] == ("book",)
    assert finding.evidence["exposure_columns"] == ("beta",)


# --- Item 4: no-intercept categorical neutralization keeps the full dummy set ----------------


def test_neutralize_without_intercept_demeans_within_every_categorical_level() -> None:
    # Hand solution: group means are a=2 and b=12, so residuals are -1, +1, -2, +2.
    result = neutralize(_panel(), exposures=("sector",), categorical=("sector",), intercept=False)

    residuals = result.frame.sort("instrument").get_column("signal").to_list()
    assert residuals == pytest.approx([-1.0, 1.0, -2.0, 2.0])
    coefficients = {
        row["level"]: row["coefficient"]  # type: ignore[index]
        for row in result.evidence.table("neutralization_coefficients")  # type: ignore[union-attr]
    }
    assert coefficients == pytest.approx({"a": 2.0, "b": 12.0})
    assert result.evidence.metadata.method_version == 2
    assert result.evidence.metrics["rank_deficient_groups"] == 0


def test_neutralize_without_intercept_matches_with_intercept_for_one_categorical() -> None:
    with_intercept = neutralize(_panel(), exposures=("sector",), categorical=("sector",))
    without = neutralize(_panel(), exposures=("sector",), categorical=("sector",), intercept=False)

    assert without.frame.get_column("signal").to_list() == pytest.approx(
        with_intercept.frame.get_column("signal").to_list()
    )


def test_neutralize_without_intercept_several_categoricals_is_full_rank_and_orthogonal() -> None:
    rng = np.random.default_rng(20_261_121)
    n = 24
    frame = pl.DataFrame(
        {
            "time": [0] * n,
            "instrument": [f"i{index:02d}" for index in range(n)],
            "signal": rng.normal(size=n),
            "sector": ["a", "b", "c"] * (n // 3),
            "region": ["x", "y"] * (n // 2),
        }
    )
    result = neutralize(
        frame,
        exposures=("sector", "region"),
        categorical=("sector", "region"),
        intercept=False,
    )
    with_intercept = neutralize(
        frame, exposures=("sector", "region"), categorical=("sector", "region")
    )

    assert result.evidence.metrics["rank_deficient_groups"] == 0
    residuals = result.frame.sort("instrument")
    for column in ("sector", "region"):
        joined = residuals.join(frame.select("instrument", column), on="instrument")
        sums = joined.group_by(column).agg(pl.col("signal").sum()).get_column("signal")
        assert sums.to_numpy() == pytest.approx(0.0, abs=1e-9)
    assert residuals.get_column("signal").to_list() == pytest.approx(
        with_intercept.frame.sort("instrument").get_column("signal").to_list()
    )
