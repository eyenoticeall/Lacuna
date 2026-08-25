from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from lacuna.exceptions import DataContractError, MethodContractError
from lacuna.regime import quantile_regimes, regime_analysis


def test_expanding_quantiles_use_only_strictly_prior_observations() -> None:
    first = quantile_regimes(
        pl.DataFrame({"time": range(6), "value": [1.0, 2.0, 3.0, 4.0, 5.0, 100.0]}),
        method="expanding",
        min_history=3,
    )
    changed_future = quantile_regimes(
        pl.DataFrame({"time": range(6), "value": [1.0, 2.0, 3.0, 4.0, 5.0, 10_000.0]}),
        method="expanding",
        min_history=3,
    )

    first_rows = first.table("regimes")
    changed_rows = changed_future.table("regimes")
    assert [row["threshold_upper"] for row in first_rows] == [  # type: ignore[index, union-attr]
        row["threshold_upper"]
        for row in changed_rows  # type: ignore[index, union-attr]
    ]
    assert [row["regime"] for row in first_rows[:3]] == [  # type: ignore[index]
        "unknown",
        "unknown",
        "unknown",
    ]
    assert first_rows[5]["history_count"] == 5  # type: ignore[index]
    assert "REGIME_THRESHOLDS_POINT_IN_TIME" in {finding.code for finding in first.findings}


def test_rolling_quantiles_limit_history_and_are_seed_free() -> None:
    result = quantile_regimes(
        pl.DataFrame({"time": range(8), "value": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]}),
        method="rolling",
        min_history=3,
        window=3,
    )

    rows = result.table("regimes")
    assert rows[-1]["history_count"] == 3  # type: ignore[index]
    assert rows[-1]["threshold_upper"] == pytest.approx(6.5)  # type: ignore[index]


def test_retrospective_quantiles_are_explicitly_descriptive() -> None:
    result = quantile_regimes(
        pl.DataFrame({"time": range(4), "value": [1.0, 2.0, 3.0, 100.0]}),
        method="retrospective",
    )

    assert result.metrics["unknown_rows"] == 0
    assert "REGIME_RETROSPECTIVE_THRESHOLDS" in {finding.code for finding in result.findings}


def test_quantile_regimes_detect_future_source_availability() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    result = quantile_regimes(
        pl.DataFrame(
            {
                "time": [start, start + timedelta(days=1)],
                "available": [start, start + timedelta(days=2)],
                "value": [1.0, 2.0],
            }
        ),
        method="fixed",
        lower_threshold=0.5,
        upper_threshold=1.5,
        available_time="available",
    )

    assert result.metrics["future_available_rows"] == 1
    rows = result.table("regimes")
    assert rows[0]["time"] == "2024-01-01T00:00:00Z"  # type: ignore[index]
    assert rows[1]["available"] == "2024-01-03T00:00:00Z"  # type: ignore[index]
    assert "REGIME_SOURCE_NOT_AVAILABLE" in {finding.code for finding in result.findings}


def test_quantile_regime_contracts_reject_invalid_thresholds_and_time_duplicates() -> None:
    with pytest.raises(MethodContractError, match="strictly ordered"):
        quantile_regimes(
            pl.DataFrame({"time": [0], "value": [1.0]}),
            method="fixed",
            lower_threshold=2.0,
            upper_threshold=1.0,
        )
    with pytest.raises(DataContractError, match="duplicate"):
        quantile_regimes(
            pl.DataFrame({"time": [0, 0], "value": [1.0, 2.0]}),
            method="expanding",
            min_history=1,
        )


def test_regime_analysis_detects_planted_outcome_concentration() -> None:
    frame = pl.DataFrame(
        {
            "time": range(12),
            "regime": ["ordinary"] * 10 + ["rare"] * 2,
            "outcome": [1.0] * 10 + [10.0] * 2,
        }
    )
    result = regime_analysis(
        frame,
        classification_mode="retrospective",
        min_observations=2,
        concentration_threshold=0.6,
    )

    rows = result.table("conditional_evidence")
    rare = next(row for row in rows if row["regime"] == "rare")  # type: ignore[union-attr]
    assert rare["observation_share"] == pytest.approx(1 / 6)
    assert rare["absolute_outcome_share"] == pytest.approx(2 / 3)
    assert rare["leave_one_regime_out_total"] == pytest.approx(10.0)
    assert result.metrics["top_regime"] == "rare"
    assert {finding.code for finding in result.findings} >= {
        "REGIME_OUTCOME_CONCENTRATION",
        "REGIME_ANALYSIS_RETROSPECTIVE",
    }


def test_regime_analysis_keeps_unknown_and_small_regimes_visible() -> None:
    result = regime_analysis(
        pl.DataFrame(
            {
                "time": [0, 1, 2],
                "regime": ["known", "unknown", "known"],
                "outcome": [0.1, None, -0.2],
            }
        ),
        classification_mode="point_in_time",
        min_observations=3,
    )

    rows = result.table("conditional_evidence")
    assert {row["regime"] for row in rows} == {"known", "unknown"}  # type: ignore[union-attr]
    assert result.metrics["excluded_outcomes"] == 1
    assert {finding.code for finding in result.findings} >= {
        "REGIME_INSUFFICIENT_EVIDENCE",
        "REGIME_UNKNOWN_CLASSIFICATION",
        "REGIME_AVAILABILITY_UNKNOWN",
    }


def test_regime_analysis_validates_availability_and_overlap_semantics() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    leakage = regime_analysis(
        pl.DataFrame(
            {
                "time": [start, start + timedelta(days=1)],
                "available": [start, start + timedelta(days=2)],
                "regime": ["low", "high"],
                "outcome": [0.1, 0.2],
            }
        ),
        classification_mode="point_in_time",
        available_time="available",
        min_observations=1,
    )
    overlap = regime_analysis(
        pl.DataFrame(
            {
                "time": [0, 0, 1],
                "regime": ["trend", "low_vol", "trend"],
                "outcome": [0.1, 0.1, 0.2],
            }
        ),
        classification_mode="retrospective",
        mutually_exclusive=False,
        min_observations=1,
    )

    assert "REGIME_AVAILABILITY_LEAKAGE" in {finding.code for finding in leakage.findings}
    observations = leakage.table("observations")
    assert observations[0]["time"] == "2024-01-01T00:00:00Z"  # type: ignore[index]
    assert "REGIME_LABELS_OVERLAP" in {finding.code for finding in overlap.findings}
    with pytest.raises(DataContractError, match="duplicate"):
        regime_analysis(
            pl.DataFrame(
                {
                    "time": [0, 0],
                    "regime": ["trend", "low_vol"],
                    "outcome": [0.1, 0.1],
                }
            ),
            classification_mode="retrospective",
        )
