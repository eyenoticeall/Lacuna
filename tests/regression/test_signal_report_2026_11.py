"""Regression tests for signal, label, and study defects reported against v0.14.1."""

from __future__ import annotations

import polars as pl
import pytest

import lacuna as lc
from lacuna.cv import CombinatorialPurgedKFold, PurgedKFold
from lacuna.labels import forward_returns
from lacuna.signal import BucketSpec, ic, quantiles
from lacuna.types import AnalysisResult, Finding, FindingState, ResultMetadata


def _panel(n_times: int = 30, n_instruments: int = 6) -> tuple[pl.DataFrame, pl.DataFrame]:
    prices = pl.DataFrame(
        {
            "time": [t for i in range(n_instruments) for t in range(n_times)],
            "instrument": [f"I{i}" for i in range(n_instruments) for _ in range(n_times)],
            "close": [
                100.0 + 4.0 * i + t * (0.3 + 0.05 * i) + 0.2 * ((t + i) % 3)
                for i in range(n_instruments)
                for t in range(n_times)
            ],
        }
    )
    signal = pl.DataFrame(
        {
            "time": [t for t in range(n_times) for _ in range(n_instruments)],
            "instrument": [f"I{i}" for _ in range(n_times) for i in range(n_instruments)],
            "signal": [
                float(((t + 2 * i) % 11) - 5) for t in range(n_times) for i in range(n_instruments)
            ],
        }
    )
    return signal, prices


def _study(signal: pl.DataFrame, prices: pl.DataFrame, **kwargs: object) -> lc.SignalStudy:
    return lc.SignalStudy(
        signal=signal,
        prices=prices,
        horizons=("1D", "5D"),
        signal_observed_at="open",
        entry="current_close",
        price_adjustment="total_return_adjusted",
        quantiles=3,
        **kwargs,  # type: ignore[arg-type]
    )


def test_study_with_renamed_instrument_column_matches_canonical_study() -> None:
    """A renamed identifier column must not break label-consuming study methods.

    ``forward_returns`` always writes ``instrument``; the study used to look for the source
    name in the label frame and raise ``missing required columns: ticker``.
    """

    signal, prices = _panel()
    canonical = _study(signal, prices)
    renamed = _study(
        signal.rename({"instrument": "ticker"}),
        prices.rename({"instrument": "ticker"}),
        instrument="ticker",
    )

    assert renamed.ic().table("ic_by_horizon") == canonical.ic().table("ic_by_horizon")
    assert renamed.quantiles().table("quantile_returns") == canonical.quantiles().table(
        "quantile_returns"
    )
    assert renamed.decay().table("ic_decay") == canonical.decay().table("ic_decay")
    spec = BucketSpec.quantiles(3)
    assert (
        renamed.bucket_returns(renamed.bucketize(spec=spec)).metrics
        == canonical.bucket_returns(canonical.bucketize(spec=spec)).metrics
    )
    renamed_audit = renamed.audit(bootstrap_resamples=100, seed=7)
    canonical_audit = canonical.audit(bootstrap_resamples=100, seed=7)
    assert renamed_audit.result.metrics == canonical_audit.result.metrics


def test_missing_raise_accepts_end_of_sample_censoring() -> None:
    """``missing="raise"`` must not reject the unavoidable final-horizon censoring."""

    prices = pl.DataFrame(
        {
            "time": [0, 1, 2, 3, 4],
            "instrument": ["A"] * 5,
            "close": [10.0, 11.0, 12.0, 13.0, 14.0],
        }
    )
    raised = forward_returns(prices, horizon="1D", price_adjustment="raw", missing="raise")
    dropped = forward_returns(prices, horizon="1D", price_adjustment="raw", missing="drop")

    assert raised.frame.equals(dropped.frame)
    assert raised.frame.get_column("observation_time").to_list() == [0, 1, 2, 3]
    coverage = raised.evidence.table("coverage_by_horizon")
    assert [row["censored_rows"] for row in coverage] == [1]  # type: ignore[union-attr]
    horizon_rows = [
        row
        for row in raised.evidence.table("data_attrition")  # type: ignore[union-attr]
        if row["stage"] == "horizon_eligibility"
    ]
    # The censored tail was dropped, so the stage must not claim the ``raise`` policy.
    assert [(row["excluded_rows"], row["policy"]) for row in horizon_rows] == [(1, "drop")]


def test_missing_raise_still_rejects_null_source_prices() -> None:
    prices = pl.DataFrame(
        {
            "time": [0, 1, 2, 3, 4],
            "instrument": ["A"] * 5,
            "close": [10.0, None, 12.0, 13.0, 14.0],
        }
    )
    with pytest.raises(lc.DataContractError, match="null or NaN"):
        forward_returns(prices, horizon="1D", price_adjustment="raw", missing="raise")


def test_infinite_signal_on_an_unlabelled_row_is_rejected() -> None:
    """Infinity must be rejected on the declared input, not only on label-matched rows."""

    signal, prices = _panel()
    labels = forward_returns(prices, horizon="1D", price_adjustment="raw")
    last_time = int(signal.get_column("time").max())  # type: ignore[arg-type]
    assert last_time not in labels.frame.get_column("observation_time").to_list()
    poisoned = signal.with_columns(
        pl.when((pl.col("time") == last_time) & (pl.col("instrument") == "I0"))
        .then(float("inf"))
        .otherwise(pl.col("signal"))
        .alias("signal")
    )
    with pytest.raises(lc.DataContractError, match="signal input contains 1 rows"):
        ic(poisoned, labels, use_native=False)
    # ``quantiles`` already rejected it while bucketizing the whole signal input.
    with pytest.raises(lc.DataContractError, match="infinity"):
        quantiles(poisoned, labels, quantiles=3)


def test_decay_table_names_spread_period_count_explicitly() -> None:
    """``ic_decay`` must not leak a join-suffixed ``n_periods_right`` column."""

    signal, prices = _panel()
    table = _study(signal, prices).decay().table("ic_decay")
    columns = set(table[0])  # type: ignore[index]
    assert "n_periods_right" not in columns
    assert {"n_periods", "n_spread_periods"} <= columns


def _audit_states(report: object) -> dict[str, Finding]:
    return {finding.code: finding for finding in report.findings}  # type: ignore[attr-defined]


def test_cpcv_split_result_satisfies_purged_validation() -> None:
    """A CPCV result is purged validation evidence and must be accepted by the study audit."""

    signal, prices = _panel(n_times=80)
    study = _study(signal, prices)
    split = CombinatorialPurgedKFold(n_groups=4, n_test_groups=2).split(study.labels().frame)
    assert split.evidence.metrics["purged_observations"] > 0  # type: ignore[operator]

    for supplied in (split, split.evidence):
        report = study.audit(bootstrap_resamples=100, seed=3, split=supplied)
        finding = _audit_states(report)["PURGED_VALIDATION_SUPPLIED"]
        assert finding.state == FindingState.PASS
        assert finding.evidence["rule_version"] == 2
        assert finding.evidence["method"] == "cv.combinatorial_purged_kfold"
        assert finding.evidence["data_identity_verified"] is False


def test_unpurged_split_cannot_pass_against_a_multi_observation_inference_horizon() -> None:
    """Zero purged observations refute a split built from overlapping inference labels."""

    signal, prices = _panel(n_times=80)
    study = _study(signal, prices)
    one_day = study.labels().frame.filter(pl.col("horizon") == "1D")
    split = PurgedKFold(n_splits=3, use_native=False).split(one_day)
    assert split.evidence.metrics["purged_observations"] == 0

    overlapping = study.audit(
        bootstrap_resamples=100,
        seed=3,
        split=split,
        policies={"inference_horizon": "5D"},
    )
    finding = _audit_states(overlapping)["PURGED_VALIDATION_SUPPLIED"]
    assert finding.state == FindingState.WARN
    assert finding.evidence["purged_observations"] == 0

    # One-observation labels are half-open and never overlap the next test observation,
    # so an honest purged split of them removes nothing.
    disjoint = study.audit(bootstrap_resamples=100, seed=3, split=split)
    assert _audit_states(disjoint)["PURGED_VALIDATION_SUPPLIED"].state == FindingState.PASS


def test_unpurged_warning_is_conditional_because_sampled_labels_purge_nothing() -> None:
    """Non-overlapping sampled labels legitimately purge nothing; the rule cannot refute them.

    Every fifth 5D label is disjoint from the next, so an honest purged split removes no
    observation. The finding is therefore a warning whose message states the exception,
    never a claim that the split is wrong.
    """

    signal, prices = _panel(n_times=80)
    study = _study(signal, prices)
    sampled = study.labels().frame.filter(
        (pl.col("horizon") == "5D") & (pl.col("observation_time") % 5 == 0)
    )
    split = PurgedKFold(n_splits=3, use_native=False).split(sampled)
    assert split.evidence.metrics["purged_observations"] == 0

    report = study.audit(
        bootstrap_resamples=100, seed=3, split=split, policies={"inference_horizon": "5D"}
    )
    finding = _audit_states(report)["PURGED_VALIDATION_SUPPLIED"]
    assert finding.state == FindingState.WARN
    assert "unless the split was built on non-overlapping sampled labels" in finding.message


def test_split_evidence_without_a_purge_count_is_unknown() -> None:
    signal, prices = _panel(n_times=80)
    study = _study(signal, prices)
    bare = AnalysisResult(metadata=ResultMetadata(method="cv.purged_kfold"), metrics={})
    report = study.audit(bootstrap_resamples=100, seed=3, split=bare)
    assert _audit_states(report)["PURGED_VALIDATION_SUPPLIED"].state == FindingState.UNKNOWN
