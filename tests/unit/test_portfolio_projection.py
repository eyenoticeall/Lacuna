from __future__ import annotations

import polars as pl
import pytest

from lacuna.exceptions import DataContractError, MethodContractError
from lacuna.signal import BucketSpec, bucketize, portfolio_projection


def _signal() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "time": [0] * 4 + [1] * 4,
            "instrument": ["a", "b", "c", "d"] * 2,
            "signal": [-2.0, -1.0, 1.0, 2.0, -1.5, -0.5, 0.5, 1.5],
        }
    )


def _labels(signal: pl.DataFrame | None = None) -> pl.DataFrame:
    source = _signal() if signal is None else signal
    return source.select(
        pl.col("time").alias("observation_time"),
        "instrument",
        pl.lit("1D").alias("horizon"),
        pl.col("time").alias("label_start"),
        (pl.col("time") + 1).alias("entry_time"),
        (pl.col("time") + 1).alias("label_end"),
        (pl.col("signal") * 0.01).alias("forward_return"),
    )


def test_market_neutral_gross_one_uses_half_long_and_half_short() -> None:
    bucketed = bucketize(_signal(), spec=BucketSpec.quantiles(2))
    result = portfolio_projection(
        bucketed,
        _labels(),
        horizon="1D",
        long_buckets=(2,),
        short_buckets=(1,),
    )

    for row in result.evidence.table("exposure_reconciliation"):
        assert row["long_exposure"] == pytest.approx(0.5)
        assert row["short_exposure"] == pytest.approx(-0.5)
        assert row["gross_exposure"] == pytest.approx(1.0)
        assert row["net_exposure"] == pytest.approx(0.0)
    assert result.frame.group_by("observation_time").agg(
        pl.col("contribution").sum().alias("return")
    ).get_column("return").to_list() == pytest.approx(
        [row["portfolio_return"] for row in result.evidence.table("cohort_returns")]
    )
    assert result.metadata.parameters["compounding"] is False


def test_projection_reconciles_nonzero_net_exposure_and_is_permutation_stable() -> None:
    first_bucketed = bucketize(_signal(), spec=BucketSpec.quantiles(2))
    second_bucketed = bucketize(_signal().reverse(), spec=BucketSpec.quantiles(2))
    first = portfolio_projection(
        first_bucketed,
        _labels(),
        horizon="1D",
        long_buckets=(2,),
        short_buckets=(1,),
        weighting="rank",
        gross_exposure=1.2,
        net_exposure=0.2,
    )
    second = portfolio_projection(
        second_bucketed,
        _labels().reverse(),
        horizon="1D",
        long_buckets=(2,),
        short_buckets=(1,),
        weighting="rank",
        gross_exposure=1.2,
        net_exposure=0.2,
    )

    assert first.frame.to_dicts() == second.frame.to_dicts()
    for row in first.evidence.table("exposure_reconciliation"):
        assert row["long_exposure"] == pytest.approx(0.7)
        assert row["short_exposure"] == pytest.approx(-0.5)
        assert row["gross_exposure"] == pytest.approx(1.2)
        assert row["net_exposure"] == pytest.approx(0.2)


@pytest.mark.parametrize("weighting", ("equal", "rank", "absolute_signal"))
def test_vectorized_group_allocation_matches_literal_leg_scores(weighting: str) -> None:
    source = pl.DataFrame(
        {
            "time": [0] * 12,
            "instrument": [f"a{index}" for index in range(6)] + [f"b{index}" for index in range(6)],
            "signal": [-3.0, -2.0, -1.0, 1.0, 2.0, 3.0, -6.0, -4.0, -2.0, 2.0, 4.0, 6.0],
            "sector": ["a"] * 6 + ["b"] * 6,
        }
    )
    bucketed = bucketize(source, spec=BucketSpec.threshold(0.0), by=("time", "sector"))
    result = portfolio_projection(
        bucketed,
        _labels(source),
        horizon="1D",
        long_buckets=(2,),
        short_buckets=(1,),
        weighting=weighting,  # type: ignore[arg-type]
        group_neutral="sector",
    )

    expected: dict[str, float] = {}
    for sector in ("a", "b"):
        for leg, sign in (("long", 1.0), ("short", -1.0)):
            rows = (
                result.frame.filter((pl.col("sector") == sector) & (pl.col("leg") == leg))
                .sort("instrument")
                .select("instrument", "signal")
                .to_dicts()
            )
            values = [float(row["signal"]) for row in rows]
            if weighting == "equal":
                scores = [1.0] * len(rows)
            elif weighting == "absolute_signal":
                scores = [abs(value) for value in values]
            else:
                strengths = values if leg == "long" else [-value for value in values]
                order = {value: rank + 1.0 for rank, value in enumerate(sorted(strengths))}
                scores = [order[value] for value in strengths]
            score_sum = sum(scores)
            for row, score in zip(rows, scores, strict=True):
                expected[str(row["instrument"])] = sign * score / score_sum * 0.25

    for row in result.frame.iter_rows(named=True):
        assert float(row["target_weight"]) == pytest.approx(
            expected[str(row["instrument"])],
            abs=1e-15,
        )


def test_group_neutrality_raises_or_explicitly_drops_one_sided_groups() -> None:
    signal = pl.DataFrame(
        {
            "time": [0] * 6,
            "instrument": ["a1", "a2", "b1", "b2", "c1", "c2"],
            "signal": [-3.0, -2.0, 2.0, 3.0, -1.0, 1.0],
            "sector": ["a", "a", "b", "b", "c", "c"],
        }
    )
    bucketed = bucketize(
        signal,
        spec=BucketSpec.threshold(0.0),
        by=("time", "sector"),
    )
    labels = _labels(signal)
    with pytest.raises(DataContractError, match="one-sided group"):
        portfolio_projection(
            bucketed,
            labels,
            horizon="1D",
            long_buckets=(2,),
            short_buckets=(1,),
            group_neutral="sector",
        )

    result = portfolio_projection(
        bucketed,
        labels,
        horizon="1D",
        long_buckets=(2,),
        short_buckets=(1,),
        group_neutral="sector",
        incomplete_group_policy="drop",
    )
    assert set(result.frame.get_column("sector")) == {"c"}
    assert result.evidence.metrics["excluded_incomplete_group_rows"] == 4
    assert result.evidence.table("data_attrition")[-1]["excluded_rows"] == 4


def test_absolute_signal_zero_dispersion_falls_back_with_finding() -> None:
    signal = _signal().with_columns(
        pl.when(pl.col("instrument").is_in(["a", "b"]))
        .then(0.0)
        .otherwise(pl.col("signal"))
        .alias("signal")
    )
    bucketed = bucketize(signal, spec=BucketSpec.quantiles(2))
    result = portfolio_projection(
        bucketed,
        _labels(signal),
        horizon="1D",
        long_buckets=(2,),
        short_buckets=(1,),
        weighting="absolute_signal",
    )
    assert "PORTFOLIO_ZERO_SIGNAL_FALLBACK" in {
        finding.code for finding in result.evidence.findings
    }


def test_projection_records_label_attrition_and_rejects_invalid_contracts() -> None:
    bucketed = bucketize(_signal(), spec=BucketSpec.quantiles(2))
    incomplete_labels = _labels().filter(pl.col("instrument") != "a")
    result = portfolio_projection(
        bucketed,
        incomplete_labels,
        horizon="1D",
        long_buckets=(2,),
        short_buckets=(1,),
    )
    assert result.evidence.metrics["excluded_alignment_rows"] == 2

    with pytest.raises(MethodContractError, match="disjoint"):
        portfolio_projection(
            bucketed,
            _labels(),
            horizon="1D",
            long_buckets=(1,),
            short_buckets=(1,),
        )
    with pytest.raises(MethodContractError, match=r"abs\(net\)"):
        portfolio_projection(
            bucketed,
            _labels(),
            horizon="1D",
            long_buckets=(2,),
            short_buckets=(1,),
            gross_exposure=1.0,
            net_exposure=1.1,
        )
