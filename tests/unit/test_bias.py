from __future__ import annotations

from datetime import datetime

import polars as pl
import pytest

from lacuna.bias import (
    DatasetSpec,
    SurvivorshipStatus,
    asof_join,
    future_data_check,
    membership_at,
    revision_diagnostics,
    survivorship_diagnostics,
    universe_drift,
    validate_dataset,
)
from lacuna.exceptions import DataContractError, MethodContractError
from lacuna.experiment import fingerprint


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


def test_revision_diagnostics_groups_versions_and_validates_publication_order() -> None:
    frame = pl.DataFrame(
        {
            "instrument": ["A", "A", "B"],
            "effective_time": [1, 1, 1],
            "available_time": [2, 4, 3],
            "revision_id": [0, 1, 0],
            "value": [10.0, 11.0, 20.0],
        }
    )
    result = revision_diagnostics(
        frame,
        value="value",
        source_mode="point_in_time",
    )

    assert result.metrics["fact_count"] == 2
    assert result.metrics["revised_facts"] == 1
    assert result.metrics["maximum_versions_per_fact"] == 2
    assert {finding.code for finding in result.findings} == {"BIAS_REVISION_HISTORY_VALID"}
    assert result.table("facts")[0]["distinct_value_count"] == 2  # type: ignore[index]


def test_revision_diagnostics_exposes_latest_only_and_invalid_order() -> None:
    frame = pl.DataFrame(
        {
            "instrument": ["A", "A"],
            "effective_time": [1, 1],
            "available_time": [4, 2],
            "revision_id": [0, 1],
        }
    )
    result = revision_diagnostics(frame, source_mode="latest_only")

    assert result.metrics["order_violations"] == 1
    assert {finding.code for finding in result.findings} == {
        "BIAS_REVISION_ORDER_INVALID",
        "BIAS_REVISION_LATEST_ONLY",
    }


def test_revision_diagnostics_rejects_duplicate_version_identity() -> None:
    frame = pl.DataFrame(
        {
            "instrument": ["A", "A"],
            "effective_time": [1, 1],
            "available_time": [2, 2],
            "revision_id": [0, 0],
        }
    )
    with pytest.raises(DataContractError, match="duplicate version identities"):
        revision_diagnostics(frame, source_mode="point_in_time")

    republished = frame.with_columns(pl.Series("available_time", [2, 3]))
    with pytest.raises(DataContractError, match="duplicate version identities"):
        revision_diagnostics(republished, source_mode="point_in_time")


def test_survivorship_diagnostics_requires_and_preserves_delisted_history() -> None:
    frame = pl.DataFrame(
        {
            "index": ["LAC", "LAC", "LAC"],
            "instrument": ["A", "A", "B"],
            "valid_from": [1, 3, 1],
            "valid_to": pl.Series([3, None, None], dtype=pl.Int64),
            "available_time": [1, 3, 1],
            "delisted": [True, False, False],
        }
    )
    result = survivorship_diagnostics(
        frame,
        delisted="delisted",
        source_status=SurvivorshipStatus.CONFIRMED_SAFE,
        includes_delisted=True,
    )

    assert result.metrics["delisted_rows"] == 1
    assert result.metrics["overlapping_intervals"] == 0
    assert {finding.code for finding in result.findings} == {"BIAS_SURVIVORSHIP_SAFE"}


def test_survivorship_diagnostics_never_converts_unknown_to_pass() -> None:
    frame = pl.DataFrame(
        {
            "index": ["LAC"],
            "instrument": ["A"],
            "valid_from": [1],
            "valid_to": pl.Series([None], dtype=pl.Int64),
            "available_time": [1],
        }
    )
    unknown = survivorship_diagnostics(frame)
    biased = survivorship_diagnostics(frame, source_status="confirmed_biased")

    assert [finding.state.value for finding in unknown.findings] == ["UNKNOWN"]
    assert [finding.state.value for finding in biased.findings] == ["FAIL"]
    with pytest.raises(MethodContractError, match="includes_delisted=True"):
        survivorship_diagnostics(frame, source_status="confirmed_safe")


def test_survivorship_diagnostics_preserves_all_null_availability_as_unknown() -> None:
    frame = pl.DataFrame(
        {
            "index": ["LAC"],
            "instrument": ["A"],
            "valid_from": [1],
            "valid_to": [None],
            "available_time": [None],
        }
    )
    result = survivorship_diagnostics(frame)

    assert result.metrics["missing_availability_rows"] == 1
    assert {finding.code for finding in result.findings} == {
        "BIAS_MEMBERSHIP_AVAILABILITY_UNKNOWN",
        "BIAS_SURVIVORSHIP_UNKNOWN",
    }


def test_survivorship_diagnostics_detects_overlap_and_late_availability() -> None:
    frame = pl.DataFrame(
        {
            "index": ["LAC", "LAC"],
            "instrument": ["A", "A"],
            "valid_from": [1, 2],
            "valid_to": [3, 4],
            "available_time": [1, 3],
        }
    )
    result = survivorship_diagnostics(frame)

    assert result.metrics["overlapping_intervals"] == 1
    assert result.metrics["late_availability_rows"] == 1
    assert {finding.code for finding in result.findings} == {
        "BIAS_MEMBERSHIP_INTERVAL_OVERLAP",
        "BIAS_MEMBERSHIP_LATE_AVAILABILITY",
        "BIAS_SURVIVORSHIP_UNKNOWN",
    }


def test_membership_at_uses_half_open_boundaries_and_availability_firewall() -> None:
    frame = pl.DataFrame(
        {
            "index": ["LAC", "LAC", "LAC"],
            "instrument": ["A", "A", "B"],
            "valid_from": [1, 3, 1],
            "valid_to": pl.Series([3, None, None], dtype=pl.Int64),
            "available_time": [1, 3, 4],
            "generation": ["old", "new", "future-known"],
        }
    )
    result = membership_at(
        frame,
        as_of=3,
        source_status="confirmed_safe",
    )

    assert result.frame.get_column("instrument").to_list() == ["A"]
    assert result.frame.item(0, "generation") == "new"
    assert result.evidence.metrics["active_candidate_rows"] == 2
    assert result.evidence.metrics["not_yet_available_rows"] == 1
    assert {finding.code for finding in result.evidence.findings} == {
        "BIAS_MEMBERSHIP_NOT_YET_AVAILABLE"
    }


def test_membership_at_rejects_structurally_ambiguous_intervals() -> None:
    frame = pl.DataFrame(
        {
            "index": ["LAC", "LAC"],
            "instrument": ["A", "A"],
            "valid_from": [1, 2],
            "valid_to": [4, 3],
            "available_time": [1, 2],
        }
    )
    with pytest.raises(DataContractError, match="non-overlapping"):
        membership_at(frame, as_of=2)


def test_universe_drift_reports_additions_removals_and_unknown_source() -> None:
    frame = pl.DataFrame(
        {
            "snapshot_time": [1, 1, 2, 2, 3, 3, 3],
            "instrument": ["A", "B", "B", "C", "B", "C", "D"],
        }
    )
    result = universe_drift(frame, warning_threshold=0.5)
    transitions = result.table("transitions")

    assert result.metrics["snapshots"] == 3
    assert result.metrics["transitions"] == 2
    assert transitions[0]["additions"] == 1  # type: ignore[index]
    assert transitions[0]["removals"] == 1  # type: ignore[index]
    assert transitions[0]["jaccard"] == pytest.approx(1 / 3)  # type: ignore[index]
    assert transitions[1]["drift"] == pytest.approx(1 / 3)  # type: ignore[index]
    assert {finding.code for finding in result.findings} == {
        "BIAS_UNIVERSE_DRIFT_HIGH",
        "BIAS_SURVIVORSHIP_UNKNOWN",
    }


def test_universe_drift_rejects_duplicate_snapshot_membership() -> None:
    frame = pl.DataFrame(
        {
            "snapshot_time": [1, 1],
            "instrument": ["A", "A"],
        }
    )
    with pytest.raises(DataContractError, match="duplicate membership"):
        universe_drift(frame)


def test_universe_drift_self_join_matches_literal_multi_universe_sets() -> None:
    frame = pl.concat(
        [
            pl.DataFrame(
                {
                    "universe": ["u2", "u2", "u1", "u2", "u1"],
                    "snapshot_time": [2, 1, 3, 3, 1],
                    "instrument": ["C", "A", "Y", "E", "X"],
                }
            ),
            pl.DataFrame(
                {
                    "universe": ["u2", "u2", "u2", "u1"],
                    "snapshot_time": [2, 1, 3, 3],
                    "instrument": ["D", "B", "C", "X"],
                }
            ),
        ],
        rechunk=False,
    )
    result = universe_drift(
        frame,
        universe="universe",
        source_status=SurvivorshipStatus.CONFIRMED_SAFE,
        warning_threshold=0.5,
    )

    assert result.table("transitions") == [
        {
            "previous_time": 1,
            "current_time": 2,
            "previous_size": 2,
            "current_size": 2,
            "additions": 2,
            "removals": 2,
            "retained": 0,
            "retention": 0.0,
            "jaccard": 0.0,
            "drift": 1.0,
            "universe": "u2",
        },
        {
            "previous_time": 2,
            "current_time": 3,
            "previous_size": 2,
            "current_size": 2,
            "additions": 1,
            "removals": 1,
            "retained": 1,
            "retention": 0.5,
            "jaccard": 1 / 3,
            "drift": 1.0 - 1 / 3,
            "universe": "u2",
        },
        {
            "previous_time": 1,
            "current_time": 3,
            "previous_size": 1,
            "current_size": 2,
            "additions": 1,
            "removals": 0,
            "retained": 1,
            "retention": 1.0,
            "jaccard": 0.5,
            "drift": 0.5,
            "universe": "u1",
        },
    ]
    assert result.metadata.input_fingerprint == fingerprint(
        frame.to_dicts(),
        namespace="universe-drift",
    )


def test_validate_dataset_reports_structural_and_temporal_defects() -> None:
    spec = DatasetSpec(
        name="fundamentals",
        required=("instrument", "effective_time", "available_time", "value"),
        keys=("instrument", "effective_time"),
        non_null=("instrument", "value"),
        numeric=("value",),
        temporal=("effective_time", "available_time"),
        temporal_order=(("effective_time", "available_time"),),
    )
    clean = validate_dataset(
        pl.DataFrame(
            {
                "instrument": ["A", "B"],
                "effective_time": [1, 2],
                "available_time": [2, 2],
                "value": [1.0, 2.0],
            }
        ),
        spec=spec,
    )
    broken = validate_dataset(
        pl.DataFrame(
            {
                "instrument": ["A", "A", None],
                "effective_time": [2, 2, 3],
                "available_time": [1, 1, 4],
                "value": [float("inf"), float("inf"), None],
            }
        ),
        spec=spec,
    )

    assert {finding.code for finding in clean.findings} == {"DATASET_CONTRACT_VALID"}
    assert {finding.code for finding in broken.findings} == {
        "DATASET_NULL_CONSTRAINT_FAILED",
        "DATASET_KEY_NOT_UNIQUE",
        "DATASET_NONFINITE_VALUES",
        "DATASET_TEMPORAL_ORDER_INVALID",
    }
    assert broken.metrics["duplicate_key_rows"] == 2
    assert broken.metrics["nonfinite_values"] == 2


def test_validate_dataset_returns_missing_column_findings_and_validates_spec() -> None:
    spec = DatasetSpec(name="prices", required=("time", "close"), numeric=("close",))
    result = validate_dataset(pl.DataFrame({"time": [1]}), spec=spec)

    assert result.metrics["missing_required_columns"] == 1
    assert {finding.code for finding in result.findings} == {"DATASET_REQUIRED_COLUMNS_MISSING"}
    with pytest.raises(MethodContractError, match="declared in required"):
        DatasetSpec(name="invalid", required=("time",), numeric=("close",))
    with pytest.raises(MethodContractError, match="declared in temporal"):
        DatasetSpec(
            name="invalid-order",
            required=("effective", "available"),
            temporal_order=(("effective", "available"),),
        )
