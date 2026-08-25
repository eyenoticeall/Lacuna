from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from lacuna.exceptions import DataContractError, MethodContractError
from lacuna.labels import forward_returns
from lacuna.types import FindingState


def _prices() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "time": [0, 1, 2, 3, 0, 1, 2, 3],
            "instrument": ["A"] * 4 + ["B"] * 4,
            "open": [10.0, 11.0, 12.0, 13.0, 20.0, 19.0, 18.0, 17.0],
            "close": [10.5, 11.5, 12.5, 13.5, 19.5, 18.5, 17.5, 16.5],
        }
    )


def test_close_to_close_forward_returns_have_explicit_intervals() -> None:
    result = forward_returns(
        _prices(),
        horizons=["1D", "2D"],
        price_adjustment="split_adjusted",
    )

    labels = result.frame
    first = labels.filter(
        (pl.col("instrument") == "A")
        & (pl.col("observation_time") == 0)
        & (pl.col("horizon") == "2D")
    ).row(0, named=True)
    assert first["label_start"] == 0
    assert first["entry_time"] == 0
    assert first["label_end"] == 2
    assert first["forward_return"] == pytest.approx(12.5 / 10.5 - 1.0)
    assert result.evidence.metrics["n_labels"] == 10


def test_next_open_uses_the_next_observation_and_rejects_same_close() -> None:
    next_open = forward_returns(
        _prices(),
        horizon="1D",
        signal_time="close",
        entry="next_open",
        price_adjustment="raw",
    ).frame
    first = next_open.filter(pl.col("instrument") == "A").row(0, named=True)
    assert first["label_start"] == 0
    assert first["entry_time"] == 1
    assert first["label_end"] == 1
    assert first["forward_return"] == pytest.approx(11.5 / 11.0 - 1.0)

    with pytest.raises(MethodContractError, match="cannot use the same close"):
        forward_returns(
            _prices(),
            horizon="1D",
            signal_time="close",
            entry="current_close",
        )


def test_missing_price_censors_a_horizon_without_collapsing_time() -> None:
    prices = pl.DataFrame(
        {
            "time": [0, 1, 2, 3],
            "instrument": ["A", "A", "A", "A"],
            "close": [10.0, None, 30.0, 40.0],
        }
    )
    result = forward_returns(
        prices,
        horizon="1D",
        price_adjustment="raw",
        missing="drop",
    )
    assert result.frame.get_column("observation_time").to_list() == [2]
    assert result.frame.get_column("forward_return").to_list() == pytest.approx([1 / 3])


def test_missing_price_raise_policy_fails_before_construction() -> None:
    prices = _prices().with_columns(
        pl.when((pl.col("instrument") == "A") & (pl.col("time") == 1))
        .then(None)
        .otherwise(pl.col("close"))
        .alias("close")
    )
    with pytest.raises(DataContractError, match="null or NaN"):
        forward_returns(prices, horizon="1D", missing="raise")


def test_duplicate_bars_are_rejected() -> None:
    prices = pl.concat([_prices(), _prices().head(1)])
    with pytest.raises(DataContractError, match="duplicate rows"):
        forward_returns(prices, horizon="1D")


def test_unknown_adjustment_and_delisting_are_explicit_findings() -> None:
    result = forward_returns(_prices(), horizon="1D")
    states = {finding.code: finding.state for finding in result.evidence.findings}
    assert states == {
        "PRICE_ADJUSTMENT_UNKNOWN": FindingState.UNKNOWN,
        "DELISTING_RETURNS_UNKNOWN": FindingState.UNKNOWN,
    }


def test_numpy_price_input_requires_and_uses_explicit_schema() -> None:
    values = np.array(
        [
            [0.0, 1.0, 10.0],
            [1.0, 1.0, 11.0],
            [2.0, 1.0, 12.0],
        ]
    )
    result = forward_returns(
        values,
        schema=["time", "instrument", "close"],
        horizon=1,
        price_adjustment="raw",
    )
    assert result.frame.get_column("forward_return").to_list() == pytest.approx([0.1, 1 / 11])


@pytest.mark.parametrize("horizon", [0, "0D", "5Y", "junk"])
def test_invalid_or_unsupported_horizons_are_rejected(horizon: object) -> None:
    with pytest.raises(MethodContractError):
        forward_returns(_prices(), horizon=horizon)  # type: ignore[arg-type]


def test_non_positive_and_infinite_prices_are_rejected() -> None:
    for bad in (0.0, -1.0, float("inf")):
        prices = _prices().with_columns(
            pl.when((pl.col("instrument") == "A") & (pl.col("time") == 1))
            .then(bad)
            .otherwise(pl.col("close"))
            .alias("close")
        )
        with pytest.raises(DataContractError):
            forward_returns(prices, horizon="1D")
