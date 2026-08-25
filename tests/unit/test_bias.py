from __future__ import annotations

from datetime import datetime

import polars as pl
import pytest

from lacuna.bias import asof_join, future_data_check
from lacuna.exceptions import DataContractError, MethodContractError


def test_asof_join_selects_latest_admissible_record_and_preserves_left_order() -> None:
    left = pl.DataFrame(
        {
            "decision_time": [5, 2, 3],
            "instrument": ["A", "A", "B"],
            "left_id": ["late-a", "early-a", "only-b"],
        }
    )
    right = pl.DataFrame(
        {
            "available_time": [3, 1, 4],
            "instrument": ["A", "A", "B"],
            "value": [30.0, 10.0, 40.0],
        }
    )

    result = asof_join(
        left,
        right,
        revision_mode="not_applicable",
    )

    assert result.frame.get_column("left_id").to_list() == ["late-a", "early-a", "only-b"]
    assert result.frame.get_column("value").to_list() == [30.0, 10.0, None]
    assert result.frame.get_column("available_time").to_list() == [3, 1, None]
    assert result.evidence.metrics["matched_rows"] == 2
    assert result.evidence.metrics["future_matches"] == 0
    assert result.evidence.metrics["max_information_age"] == 2
    assert {finding.code for finding in result.evidence.findings} == {"BIAS_ASOF_UNMATCHED"}


def test_exact_match_policy_controls_the_decision_boundary() -> None:
    left = pl.DataFrame({"decision_time": [2], "instrument": ["A"]})
    right = pl.DataFrame(
        {
            "available_time": [1, 2],
            "instrument": ["A", "A"],
            "value": [10, 20],
        }
    )

    exact = asof_join(left, right, revision_mode="not_applicable")
    strict = asof_join(
        left,
        right,
        revision_mode="not_applicable",
        allow_exact_matches=False,
    )

    assert exact.frame.item(0, "value") == 20
    assert strict.frame.item(0, "value") == 10
    assert exact.evidence.metrics["mean_information_age"] == 0.0
    assert strict.evidence.metrics["mean_information_age"] == 1.0


def test_revision_ties_use_explicit_revision_not_input_order() -> None:
    left = pl.DataFrame({"decision_time": [5], "instrument": ["A"]})
    right = pl.DataFrame(
        {
            "available_time": [3, 3],
            "instrument": ["A", "A"],
            "revision_id": [2, 1],
            "value": [200, 100],
        }
    )
    first = asof_join(
        left,
        right,
        revision="revision_id",
        revision_mode="point_in_time",
    )
    shuffled = asof_join(
        left,
        right.reverse(),
        revision="revision_id",
        revision_mode="point_in_time",
    )

    assert first.frame.item(0, "value") == 200
    assert shuffled.frame.equals(first.frame)
    assert first.evidence.metrics["revision_tie_rows"] == 2
    assert {finding.code for finding in first.evidence.findings} == {"BIAS_ASOF_TEMPORAL_FIREWALL"}


def test_ambiguous_or_duplicate_revision_ties_are_rejected() -> None:
    left = pl.DataFrame({"decision_time": [5], "instrument": ["A"]})
    right = pl.DataFrame(
        {
            "available_time": [3, 3],
            "instrument": ["A", "A"],
            "revision_id": [1, 1],
            "value": [100, 200],
        }
    )
    with pytest.raises(DataContractError, match="provide revision"):
        asof_join(left, right, revision_mode="unknown")
    with pytest.raises(DataContractError, match="duplicate identity/availability/revision"):
        asof_join(
            left,
            right,
            revision="revision_id",
            revision_mode="point_in_time",
        )


def test_tolerance_rejects_stale_matches_and_unmatched_policies_are_explicit() -> None:
    left = pl.DataFrame({"decision_time": [2, 5], "instrument": ["A", "A"], "left_id": [1, 2]})
    right = pl.DataFrame({"available_time": [1, 3], "instrument": ["A", "A"], "value": [10, 30]})
    kept = asof_join(
        left,
        right,
        tolerance=1,
        revision_mode="not_applicable",
    )
    dropped = asof_join(
        left,
        right,
        tolerance=1,
        unmatched="drop",
        revision_mode="not_applicable",
    )

    assert kept.frame.get_column("value").to_list() == [10, None]
    assert kept.evidence.metrics["stale_matches_rejected"] == 1
    assert dropped.frame.get_column("left_id").to_list() == [1]
    assert dropped.evidence.metrics["output_rows"] == 1
    with pytest.raises(DataContractError, match="1 unmatched"):
        asof_join(
            left,
            right,
            tolerance=1,
            unmatched="raise",
            revision_mode="not_applicable",
        )


def test_asof_join_records_revision_uncertainty() -> None:
    left = pl.DataFrame({"decision_time": [2], "instrument": ["A"]})
    right = pl.DataFrame({"available_time": [1], "instrument": ["A"], "value": [10]})
    latest = asof_join(left, right, revision_mode="latest_only")
    unknown = asof_join(left, right)

    assert {finding.code for finding in latest.evidence.findings} == {"BIAS_REVISION_LATEST_ONLY"}
    assert {finding.code for finding in unknown.evidence.findings} == {
        "BIAS_REVISION_STATUS_UNKNOWN"
    }


def test_timezone_aware_offset_boundaries_remain_ordered_and_serializable() -> None:
    left = pl.DataFrame(
        {
            "decision_time": [
                datetime.fromisoformat("2024-03-10T03:00:00-04:00"),
                datetime.fromisoformat("2024-11-03T01:30:00-05:00"),
            ],
            "instrument": ["A", "A"],
        }
    )
    right = pl.DataFrame(
        {
            "available_time": [
                datetime.fromisoformat("2024-03-10T01:59:59-05:00"),
                datetime.fromisoformat("2024-11-03T01:30:00-04:00"),
            ],
            "instrument": ["A", "A"],
            "value": ["spring", "fall-first"],
        }
    )

    result = asof_join(left, right, revision_mode="not_applicable")

    assert result.frame.get_column("value").to_list() == ["spring", "fall-first"]
    assert result.evidence.metrics["future_matches"] == 0
    assert "2024-03-10" in result.evidence.to_json()


def test_asof_join_validates_contracts() -> None:
    left = pl.DataFrame({"decision_time": [1], "instrument": ["A"]})
    right = pl.DataFrame({"available_time": [1.0], "instrument": ["A"], "value": [10]})
    with pytest.raises(DataContractError, match="matching dtypes"):
        asof_join(left, right)
    with pytest.raises(MethodContractError, match="non-negative"):
        asof_join(
            left,
            right.with_columns(pl.col("available_time").cast(pl.Int64)),
            tolerance=-1,
        )
    with pytest.raises(MethodContractError, match="revision_mode"):
        asof_join(
            left,
            right.with_columns(pl.col("available_time").cast(pl.Int64)),
            revision_mode="safe",  # type: ignore[arg-type]
        )


def test_future_data_check_detects_one_nanosecond_and_materiality() -> None:
    time_dtype = pl.Datetime("ns", "UTC")
    frame = pl.DataFrame(
        {
            "row_id": ["safe", "equal", "future"],
            "instrument": ["A", "B", "C"],
            "decision_time": pl.Series([10, 20, 30]).cast(time_dtype),
            "available_time": pl.Series([9, 20, 31]).cast(time_dtype),
            "weight": [1.0, 2.0, 7.0],
        }
    )
    result = future_data_check(frame, row_id="row_id", materiality="weight")

    assert result.metrics["future_rows"] == 1
    assert result.metrics["equal_boundary_rows"] == 1
    assert result.metrics["future_materiality_fraction"] == pytest.approx(0.7)
    assert result.table("future_rows")[0]["row_id"] == "future"  # type: ignore[index]
    assert {finding.code for finding in result.findings} == {"BIAS_FUTURE_DATA"}


def test_future_data_check_keeps_missing_availability_unknown() -> None:
    frame = pl.DataFrame(
        {
            "decision_time": [1, 2],
            "available_time": pl.Series([1, None], dtype=pl.Int64),
            "instrument": ["A", "B"],
        }
    )
    result = future_data_check(frame)

    assert result.metrics["future_rows"] == 0
    assert result.metrics["missing_availability_rows"] == 1
    assert {finding.code for finding in result.findings} == {"BIAS_AVAILABILITY_MISSING"}


def test_future_data_check_passes_only_complete_nonfuture_evidence() -> None:
    result = future_data_check(
        pl.DataFrame(
            {
                "decision_time": [2, 3],
                "available_time": [1, 3],
                "instrument": ["A", "B"],
            }
        )
    )
    assert {finding.code for finding in result.findings} == {"BIAS_FUTURE_DATA_CLEAR"}
