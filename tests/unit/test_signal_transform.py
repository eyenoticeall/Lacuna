from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from lacuna._signal_transform import _assign_bucket_group
from lacuna.exceptions import DataContractError, MethodContractError
from lacuna.signal import BucketSpec, bucketize, neutralize


def _signal_panel() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "time": [0] * 6 + [1] * 6,
            "instrument": [f"asset-{index}" for index in range(6)] * 2,
            "signal": [-3.0, -2.0, -1.0, 1.0, 2.0, 3.0] * 2,
            "sector": ["a", "a", "a", "b", "b", "b"] * 2,
        }
    )


def test_bucket_spec_rejects_ambiguous_edges() -> None:
    with pytest.raises(MethodContractError, match="begin at 0"):
        BucketSpec.quantiles(edges=(0.1, 0.5, 1.0))
    with pytest.raises(MethodContractError, match="strictly increasing"):
        BucketSpec.edges((-1.0, 0.0, 0.0, 1.0))


def test_balanced_bucketize_conserves_rows_and_is_permutation_stable() -> None:
    signal = _signal_panel()
    first = bucketize(signal, spec=BucketSpec.quantiles(3)).frame
    second = bucketize(signal.reverse(), spec=BucketSpec.quantiles(3)).frame

    assert first.to_dicts() == second.to_dicts()
    assert first.height == signal.height
    assert first.group_by(["observation_time", "bucket"]).len()["len"].to_list() == [2] * 6


def test_preserve_ties_never_splits_equal_values() -> None:
    signal = _signal_panel().with_columns((pl.col("signal") // 2).alias("signal"))
    result = bucketize(signal, spec=BucketSpec.quantiles(4, tie_policy="preserve"))
    groups = result.frame.group_by(["observation_time", "signal"]).agg(
        pl.col("bucket").n_unique().alias("n_buckets")
    )
    assert groups.get_column("n_buckets").to_list() == [1] * groups.height


def test_fixed_edges_raise_or_record_out_of_range_attrition() -> None:
    signal = _signal_panel()
    with pytest.raises(DataContractError, match="exclude"):
        bucketize(signal, spec=BucketSpec.edges((-2.0, 0.0, 2.0)))

    result = bucketize(
        signal,
        spec=BucketSpec.edges((-2.0, 0.0, 2.0), out_of_range="drop"),
    )
    assert result.frame.height == 8
    assert result.evidence.metrics["excluded_bucket_rows"] == 4
    assert result.evidence.table("data_attrition")[-1]["excluded_rows"] == 4  # type: ignore[index]


def test_split_aware_quantiles_keep_sign_sides_separate() -> None:
    result = bucketize(
        _signal_panel(),
        spec=BucketSpec.quantiles(4, split_at=0.0),
    ).frame
    assert result.filter(pl.col("signal") < 0).get_column("bucket").max() == 2
    assert result.filter(pl.col("signal") > 0).get_column("bucket").min() == 3


def test_grouped_bucketize_requires_availability_evidence_or_marks_unknown() -> None:
    signal = _signal_panel()
    unknown = bucketize(signal, spec=BucketSpec.quantiles(2), by=("time", "sector"))
    assert {finding.code for finding in unknown.evidence.findings} == {"GROUP_AVAILABILITY_UNKNOWN"}

    available = signal.with_columns(pl.col("time").alias("available"))
    verified = bucketize(
        available,
        spec=BucketSpec.quantiles(2),
        by=("time", "sector"),
        available_time="available",
    )
    assert {finding.code for finding in verified.evidence.findings} == {
        "GROUP_AVAILABILITY_VERIFIED"
    }

    future = available.with_columns((pl.col("time") + 1).alias("available"))
    with pytest.raises(DataContractError, match="available after observation"):
        bucketize(
            future,
            spec=BucketSpec.quantiles(2),
            by=("time", "sector"),
            available_time="available",
        )


@pytest.mark.parametrize(
    "spec",
    (
        BucketSpec.quantiles(4),
        BucketSpec.quantiles(4, tie_policy="preserve"),
        BucketSpec.quantiles(4, split_at=0.0),
        BucketSpec.equal_width(4),
        BucketSpec.edges((-4.0, -1.0, 1.0, 4.0), out_of_range="drop"),
        BucketSpec.threshold(0.0, equal_to="lower"),
    ),
)
@pytest.mark.parametrize("ascending", (True, False))
def test_polars_bucket_plan_matches_literal_group_oracle(
    spec: BucketSpec,
    ascending: bool,
) -> None:
    rng = np.random.default_rng(91_009)
    frame = pl.DataFrame(
        {
            "time": np.repeat(np.arange(5), 24),
            "instrument": np.tile(np.arange(24), 5),
            "signal": np.round(rng.normal(size=120), 1) * 2.0,
        }
    )
    expected_groups: list[pl.DataFrame] = []
    for group in (
        frame.rename({"time": "observation_time"})
        .sort(["observation_time", "instrument"])
        .partition_by("observation_time", maintain_order=True)
    ):
        expected, _ = _assign_bucket_group(group, spec, ascending=ascending)
        expected_groups.append(expected)
    expected = pl.concat(expected_groups).sort(["observation_time", "bucket", "instrument"])

    observed = bucketize(frame, spec=spec, ascending=ascending).frame
    assert observed.to_dicts() == expected.to_dicts()


def test_polars_bucket_plan_drops_only_invalid_groups_under_explicit_policy() -> None:
    frame = pl.DataFrame(
        {
            "time": [0, 0, 1, 1, 1, 1],
            "instrument": [0, 1, 0, 1, 2, 3],
            "signal": [0.0, 1.0, 0.0, 1.0, 2.0, 3.0],
        }
    )
    result = bucketize(
        frame,
        spec=BucketSpec.quantiles(4),
        small_group_policy="drop",
    )

    assert result.frame.get_column("observation_time").unique().to_list() == [1]
    assert result.evidence.metrics["excluded_bucket_rows"] == 2
    assert result.evidence.metrics["excluded_groups"] == 1


def test_neutralization_matches_hand_residuals_and_weighted_orthogonality() -> None:
    frame = pl.DataFrame(
        {
            "time": [0] * 6,
            "instrument": list(range(6)),
            "signal": [1.1, 2.0, 3.2, 3.9, 5.1, 5.8],
            "beta": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            "weight": [1.0, 1.0, 2.0, 2.0, 3.0, 3.0],
            "available": [0] * 6,
        }
    )
    result = neutralize(
        frame,
        exposures=("beta",),
        weight="weight",
        available_time="available",
    )
    output = result.frame
    residual = output.get_column("signal").to_numpy()
    source = frame.sort("instrument")
    design = np.column_stack([np.ones(frame.height), source.get_column("beta").to_numpy()])
    weights = source.get_column("weight").to_numpy()
    assert design.T @ (weights * residual) == pytest.approx([0.0, 0.0], abs=1e-10)
    assert result.evidence.metrics["retained_rows"] == 6


def test_neutralization_categorical_encoding_and_rank_deficiency_are_explicit() -> None:
    frame = (
        _signal_panel()
        .head(6)
        .with_columns(
            pl.col("signal").alias("duplicate"),
            pl.col("time").alias("available"),
        )
    )
    result = neutralize(
        frame,
        exposures=("signal", "duplicate", "sector"),
        categorical=("sector",),
        available_time="available",
        min_residual_df=1,
    )
    assert result.evidence.metrics["rank_deficient_groups"] == 1
    assert "NEUTRALIZATION_RANK_DEFICIENT" in {finding.code for finding in result.evidence.findings}


def test_neutralization_rejects_nonpositive_weights_and_insufficient_df() -> None:
    frame = _signal_panel().head(3).with_columns(pl.lit(0.0).alias("weight"))
    with pytest.raises(DataContractError, match="weights must be positive"):
        neutralize(frame, exposures=("sector",), categorical=("sector",), weight="weight")

    with pytest.raises(DataContractError, match="residual degrees"):
        neutralize(
            _signal_panel().head(3),
            exposures=("signal",),
            min_residual_df=3,
        )
