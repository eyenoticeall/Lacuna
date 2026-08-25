from __future__ import annotations

from typing import cast

import numpy as np
import polars as pl
import pytest

from lacuna.adapters import to_polars
from lacuna.bias import asof_join
from lacuna.costs import CommissionModel, stress
from lacuna.labels import forward_returns
from lacuna.signal import ic, quantiles, turnover


def _records() -> tuple[dict[str, list[object]], dict[str, list[object]]]:
    periods = 6
    instruments = 5
    names = [f"asset-{index}" for index in range(instruments)]
    signal = {
        "time": np.repeat(np.arange(periods - 2), instruments).tolist(),
        "instrument": np.tile(names, periods - 2).tolist(),
        "signal": np.tile(np.arange(instruments, dtype=np.float64), periods - 2).tolist(),
    }
    prices = {
        "time": np.tile(np.arange(periods), instruments).tolist(),
        "instrument": np.repeat(names, periods).tolist(),
        "close": [
            100.0 * (1.0 + 0.01 * (instrument + 1)) ** time
            for instrument in range(instruments)
            for time in range(periods)
        ],
    }
    return signal, prices


def _trade_records() -> dict[str, list[object]]:
    return {
        "decision_time": [0, 0, 1, 1],
        "execution_time": [0, 0, 1, 1],
        "instrument": ["A", "B", "A", "B"],
        "side": ["buy", "sell", "sell", "buy"],
        "quantity": [10.0, -20.0, -12.0, 18.0],
        "price": [100.0, 50.0, 102.0, 49.0],
        "reference_price": [100.0, 50.0, 102.0, 49.0],
        "gross_pnl": [5.0, 4.0, -1.0, 3.0],
    }


def _point_in_time_records() -> tuple[dict[str, list[object]], dict[str, list[object]]]:
    left: dict[str, list[object]] = {
        "decision_time": [2, 5, 3],
        "instrument": ["A", "A", "B"],
        "row_id": [0, 1, 2],
    }
    right: dict[str, list[object]] = {
        "available_time": [1, 4, 4],
        "instrument": ["A", "A", "B"],
        "value": [10.0, 40.0, 30.0],
    }
    return left, right


def test_eager_and_lazy_polars_paths_are_semantically_equivalent() -> None:
    signal_data, price_data = _records()
    signal = pl.DataFrame(signal_data)
    prices = pl.DataFrame(price_data)
    eager_labels = forward_returns(
        prices,
        horizons=("1D", "2D"),
        price_adjustment="raw",
    )
    lazy_labels = forward_returns(
        prices.lazy(),
        horizons=("1D", "2D"),
        price_adjustment="raw",
    )

    assert eager_labels.frame.equals(lazy_labels.frame)
    assert (
        lazy_labels.metadata.parameters["input"]["materialized"] is True  # type: ignore[index]
    )
    eager_ic = ic(signal, eager_labels)
    lazy_ic = ic(signal.lazy(), lazy_labels.frame.lazy())
    assert eager_ic.metrics == lazy_ic.metrics
    assert eager_ic.tables == lazy_ic.tables
    eager_quantiles = quantiles(signal, eager_labels, quantiles=3)
    lazy_quantiles = quantiles(signal.lazy(), lazy_labels.frame.lazy(), quantiles=3)
    assert eager_quantiles.metrics == lazy_quantiles.metrics
    assert eager_quantiles.tables == lazy_quantiles.tables
    assert turnover(signal, quantiles=3).metrics == turnover(signal.lazy(), quantiles=3).metrics


def test_pandas_inputs_match_polars_and_record_the_edge_format() -> None:
    pd = pytest.importorskip("pandas")
    signal_data, price_data = _records()
    pandas_signal = pd.DataFrame(signal_data)
    pandas_prices = pd.DataFrame(price_data)
    polars_signal = pl.DataFrame(signal_data)
    polars_prices = pl.DataFrame(price_data)

    pandas_labels = forward_returns(
        pandas_prices,
        horizons=("1D", "2D"),
        price_adjustment="raw",
    )
    polars_labels = forward_returns(
        polars_prices,
        horizons=("1D", "2D"),
        price_adjustment="raw",
    )
    pandas_ic = ic(pandas_signal, pandas_labels, use_native=False)
    polars_ic = ic(polars_signal, polars_labels, use_native=False)

    assert pandas_labels.frame.equals(polars_labels.frame)
    assert pandas_ic.metrics == polars_ic.metrics
    assert pandas_ic.tables == polars_ic.tables
    assert pandas_labels.metadata.parameters["input"]["source_type"] == "pandas.DataFrame"  # type: ignore[index]


def test_pandas_index_is_only_included_when_explicit() -> None:
    pd = pytest.importorskip("pandas")
    source = pd.DataFrame({"signal": [0.1, 0.2]}, index=pd.Index([10, 20], name="row_id"))

    without_index = cast(pl.DataFrame, to_polars(source))
    with_index = cast(pl.DataFrame, to_polars(source, include_pandas_index=True))

    assert without_index.columns == ["signal"]
    assert with_index.columns == ["row_id", "signal"]


def test_arrow_table_and_stream_inputs_match_polars() -> None:
    pa = pytest.importorskip("pyarrow")
    signal_data, price_data = _records()
    arrow_prices = pa.table(price_data)
    arrow_signal = pa.table(signal_data)
    expected_labels = forward_returns(
        pl.DataFrame(price_data),
        horizons=("1D", "2D"),
        price_adjustment="raw",
    )
    arrow_labels = forward_returns(
        arrow_prices,
        horizons=("1D", "2D"),
        price_adjustment="raw",
    )

    assert arrow_labels.frame.equals(expected_labels.frame)
    assert arrow_labels.metadata.parameters["input"]["source_type"] == "pyarrow.Table"  # type: ignore[index]
    arrow_ic = ic(arrow_signal, arrow_labels, use_native=False)
    expected_ic = ic(pl.DataFrame(signal_data), expected_labels, use_native=False)
    assert arrow_ic.metrics == expected_ic.metrics
    assert arrow_ic.tables == expected_ic.tables

    batches = arrow_prices.to_batches(max_chunksize=7)
    reader = pa.RecordBatchReader.from_batches(arrow_prices.schema, batches)
    streamed = to_polars(reader)
    assert isinstance(streamed, pl.DataFrame | pl.LazyFrame)
    assert cast(pl.DataFrame, streamed).height == len(price_data["time"])


def test_cost_analysis_matches_eager_lazy_pandas_and_arrow_inputs() -> None:
    pd = pytest.importorskip("pandas")
    pa = pytest.importorskip("pyarrow")
    records = _trade_records()
    frame = pl.DataFrame(records)
    kwargs = {"spread_bps": (0.0, 5.0), "slippage_bps": (0.0, 5.0)}

    expected = stress(frame, **kwargs)  # type: ignore[arg-type]
    lazy = stress(frame.lazy(), **kwargs)  # type: ignore[arg-type]
    pandas = stress(pd.DataFrame(records), **kwargs)  # type: ignore[arg-type]
    arrow = stress(pa.table(records), **kwargs)  # type: ignore[arg-type]

    for result in (lazy, pandas, arrow):
        assert result.metrics == expected.metrics
        assert result.tables == expected.tables
    assert lazy.metadata.parameters["frame"]["materialized"] is True  # type: ignore[index]
    assert pandas.metadata.parameters["frame"]["source_type"] == "pandas.DataFrame"  # type: ignore[index]
    assert arrow.metadata.parameters["frame"]["source_type"] == "pyarrow.Table"  # type: ignore[index]

    assert CommissionModel(notional_bps=2.0).estimate(
        pa.table(records)
    ).total_cost == pytest.approx(CommissionModel(notional_bps=2.0).estimate(frame).total_cost)


def test_point_in_time_join_matches_eager_lazy_pandas_and_arrow_inputs() -> None:
    pd = pytest.importorskip("pandas")
    pa = pytest.importorskip("pyarrow")
    left, right = _point_in_time_records()
    expected = asof_join(
        pl.DataFrame(left),
        pl.DataFrame(right),
        revision_mode="not_applicable",
    )
    variants = (
        asof_join(
            pl.DataFrame(left).lazy(),
            pl.DataFrame(right).lazy(),
            revision_mode="not_applicable",
        ),
        asof_join(pd.DataFrame(left), pd.DataFrame(right), revision_mode="not_applicable"),
        asof_join(pa.table(left), pa.table(right), revision_mode="not_applicable"),
    )

    for result in variants:
        assert result.frame.equals(expected.frame)
        assert result.evidence.metrics == expected.evidence.metrics
        assert result.evidence.tables == expected.evidence.tables
