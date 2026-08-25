from __future__ import annotations

import math

import numpy as np
import polars as pl
import pytest

from lacuna.exceptions import DataContractError, MethodContractError
from lacuna.labels import forward_returns
from lacuna.signal import decay, ic, quantiles, turnover


def _panel(periods: int = 4, instruments: int = 6) -> tuple[pl.DataFrame, pl.DataFrame]:
    times = np.repeat(np.arange(periods), instruments)
    names = np.tile([f"asset-{index}" for index in range(instruments)], periods)
    values = np.tile(np.arange(instruments, dtype=np.float64), periods)
    signal = pl.DataFrame({"time": times, "instrument": names, "signal": values})
    labels = pl.DataFrame(
        {
            "observation_time": times,
            "instrument": names,
            "forward_return": values * 0.01 + np.repeat(np.arange(periods), instruments) * 0.001,
        }
    )
    return signal, labels


def test_pearson_ic_matches_hand_computed_groups() -> None:
    signal, labels = _panel()
    result = ic(signal, labels, method="pearson", use_native=False)
    assert result.metrics["mean_ic"] == pytest.approx(1.0)
    assert result.metrics["n_periods"] == 4
    assert len(result.table("ic_by_period")) == 4  # type: ignore[arg-type]


def test_spearman_ic_uses_average_ranks_for_ties() -> None:
    signal = np.array([1.0, 2.0, 2.0, 4.0])
    labels = np.array([1.0, 2.0, 3.0, 4.0])
    result = ic(signal, labels, method="spearman", use_native=False)
    assert result.metrics["mean_ic"] == pytest.approx(0.9486832980505138)


def test_ic_marks_constant_groups_undefined_without_serializing_nan() -> None:
    signal, labels = _panel(periods=2, instruments=4)
    signal = signal.with_columns(pl.lit(1.0).alias("signal"))
    result = ic(signal, labels, use_native=False)
    assert result.metrics["mean_ic"] is None
    assert result.metrics["undefined_groups"] == 2
    assert "NaN" not in result.to_json()


def test_ic_aligns_by_identity_not_row_order() -> None:
    signal, labels = _panel()
    shuffled = labels.reverse()
    assert ic(signal, shuffled, use_native=False).metrics["mean_ic"] == pytest.approx(1.0)


def test_ic_rejects_duplicate_signal_keys() -> None:
    signal, labels = _panel()
    duplicate = pl.concat([signal, signal.head(1)])
    with pytest.raises(DataContractError, match="duplicate rows"):
        ic(duplicate, labels)


def test_quantile_returns_spread_and_monotonicity() -> None:
    signal, labels = _panel()
    result = quantiles(signal, labels, quantiles=3)
    assert result.metrics["mean_top_bottom_spread"] == pytest.approx(0.04)
    assert result.metrics["spearman_monotonicity"] == pytest.approx(1.0)
    assert result.metrics["adjacent_order_fraction"] == 1.0
    summary = result.table("quantile_returns")
    assert sum(row["n_observations"] for row in summary) == 24  # type: ignore[union-attr]


def test_quantile_ties_are_deterministic_under_input_shuffle() -> None:
    signal, labels = _panel()
    signal = signal.with_columns((pl.col("signal") // 2).alias("signal"))
    first = quantiles(signal, labels, quantiles=3).table("quantile_returns_by_period")
    second = quantiles(signal.reverse(), labels, quantiles=3).table("quantile_returns_by_period")
    assert first == second


def test_undersized_quantile_groups_are_explicitly_rejected() -> None:
    signal, labels = _panel(instruments=2)
    with pytest.raises(DataContractError, match="at least 3"):
        quantiles(signal, labels, quantiles=3)


def test_turnover_known_static_and_reversing_ranks() -> None:
    static_signal, _ = _panel(periods=3, instruments=4)
    static_result = turnover(static_signal, quantiles=2)
    assert static_result.metrics["mean_rank_turnover"] == pytest.approx(0.0)
    assert static_result.metrics["mean_signal_autocorrelation"] == pytest.approx(1.0)

    reversing = static_signal.with_columns(
        pl.when(pl.col("time") == 1)
        .then(-pl.col("signal"))
        .otherwise(pl.col("signal"))
        .alias("signal")
    )
    reversed_result = turnover(reversing, quantiles=2)
    assert float(reversed_result.metrics["mean_rank_turnover"]) > 0.0
    assert float(reversed_result.metrics["mean_signal_autocorrelation"]) < 1.0


def test_decay_combines_ic_and_spread_by_horizon() -> None:
    periods = 8
    instruments = 6
    names = [f"asset-{index}" for index in range(instruments)]
    prices = pl.DataFrame(
        {
            "time": np.tile(np.arange(periods), instruments),
            "instrument": np.repeat(names, periods),
            "close": [
                100.0 + time * (1.0 + instrument_index * 0.2)
                for instrument_index in range(instruments)
                for time in range(periods)
            ],
        }
    )
    signal = pl.DataFrame(
        {
            "time": np.repeat(np.arange(periods - 2), instruments),
            "instrument": np.tile(names, periods - 2),
            "signal": np.tile(np.arange(instruments, dtype=np.float64), periods - 2),
        }
    )
    labels = forward_returns(
        prices,
        horizons=["1D", "2D"],
        price_adjustment="split_adjusted",
    )
    result = decay(signal, labels, quantile_count=3, use_native=False)
    table = result.table("ic_decay")
    assert [row["horizon"] for row in table] == ["1D", "2D"]  # type: ignore[union-attr]


def test_nulls_drop_pairwise_and_infinity_is_rejected() -> None:
    signal, labels = _panel()
    labels_with_null = labels.with_columns(
        pl.when((pl.col("observation_time") == 0) & (pl.col("instrument") == "asset-0"))
        .then(None)
        .otherwise(pl.col("forward_return"))
        .alias("forward_return")
    )
    result = ic(signal, labels_with_null, use_native=False)
    assert result.metrics["excluded_rows"] == 1

    labels_with_infinity = labels.with_columns(
        pl.when((pl.col("observation_time") == 0) & (pl.col("instrument") == "asset-0"))
        .then(math.inf)
        .otherwise(pl.col("forward_return"))
        .alias("forward_return")
    )
    with pytest.raises(DataContractError, match="infinity"):
        ic(signal, labels_with_infinity, use_native=False)


def test_signal_and_label_semantic_keys_must_have_matching_dtypes() -> None:
    signal, labels = _panel()
    incompatible = labels.with_columns(pl.col("observation_time").cast(pl.Int32))

    with pytest.raises(DataContractError, match="aligned semantic keys must use matching dtypes"):
        ic(signal, incompatible)


def test_external_label_interval_metadata_is_validated() -> None:
    signal, labels = _panel()
    incomplete = labels.with_columns(pl.col("observation_time").alias("label_start"))
    with pytest.raises(DataContractError, match="interval metadata is incomplete"):
        ic(signal, incomplete)

    invalid = labels.with_columns(
        pl.col("observation_time").alias("label_start"),
        pl.col("observation_time").alias("label_end"),
    )
    with pytest.raises(DataContractError, match="label_start < label_end"):
        ic(signal, invalid)


def test_signal_null_policy_is_a_method_contract() -> None:
    signal, labels = _panel()
    with pytest.raises(MethodContractError, match="null_policy"):
        ic(signal, labels, null_policy="ignore")  # type: ignore[arg-type]
