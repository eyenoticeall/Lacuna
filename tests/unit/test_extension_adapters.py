from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

import numpy as np
import polars as pl
import pytest

from lacuna.adapters import (
    BacktestSchema,
    BacktestSemantics,
    SklearnCV,
    VendorSchema,
    adapt_backtest,
    adapt_vendor,
    as_sklearn_cv,
    from_duckdb,
)
from lacuna.cv import PurgedKFold, WalkForward
from lacuna.exceptions import DataContractError, MethodContractError


class _DuckDBSource:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls: list[int] = []

    def to_arrow_reader(self, batch_size: int) -> object:
        self.calls.append(batch_size)
        return self.result


class _LegacyDuckDBSource:
    def fetch_record_batch(self, batch_size: int) -> object:
        assert batch_size == 2
        return pl.DataFrame({"value": [1, 2]})


class _BrokenDuckDBSource:
    def to_arrow_reader(self, batch_size: int) -> object:
        raise RuntimeError(batch_size)


def _semantics() -> BacktestSemantics:
    return BacktestSemantics(
        returns="net",
        return_frequency="daily",
        compounding="simple",
        position_timing="close-to-close",
        execution_delay="one session",
        price_field="close",
        price_adjustment="total_return_adjusted",
        costs="included",
        borrow="included",
        timezone="UTC",
        calendar="XNYS",
        session="regular",
        missing_instruments="retain as null",
        delistings="terminal return included",
    )


def test_duckdb_adapter_prefers_arrow_reader_and_records_materialization() -> None:
    source = _DuckDBSource(pl.DataFrame({"time": [1, 2], "value": [3.0, 4.0]}))
    result = from_duckdb(source, batch_size=2, required=("time", "value"))

    assert source.calls == [2]
    assert isinstance(result.frame, pl.DataFrame)
    assert result.columns == ("time", "value")
    assert result.lazy is False
    assert result.evidence.metadata.parameters["reader_method"] == "to_arrow_reader"
    assert result.evidence.metrics["row_count"] == 2


def test_duckdb_adapter_preserves_lazy_reader_output_when_requested() -> None:
    source = _DuckDBSource(pl.DataFrame({"value": [1]}).lazy())
    result = from_duckdb(source, collect=False)

    assert result.lazy is True
    assert result.evidence.metrics["row_count"] is None


def test_duckdb_adapter_supports_declared_legacy_path() -> None:
    result = from_duckdb(_LegacyDuckDBSource(), batch_size=2)
    assert result.evidence.metadata.parameters["reader_method"] == "fetch_record_batch_legacy"


@pytest.mark.parametrize("batch_size", [True, 0, 1.5])
def test_duckdb_adapter_rejects_invalid_batch_sizes(batch_size: object) -> None:
    with pytest.raises(MethodContractError, match="positive integer"):
        from_duckdb(_DuckDBSource(pl.DataFrame()), batch_size=batch_size)  # type: ignore[arg-type]


def test_duckdb_adapter_wraps_producer_failures_and_rejects_unknown_objects() -> None:
    with pytest.raises(DataContractError, match="failed to produce"):
        from_duckdb(_BrokenDuckDBSource())
    with pytest.raises(DataContractError, match="to_arrow_reader"):
        from_duckdb(object())


def test_vendor_schema_normalizes_names_and_freezes_caller_mapping() -> None:
    mapping = {
        "instrument": "ticker",
        "available_time": "published_at",
        "revision_id": "revision",
        "value": "metric",
    }
    schema = VendorSchema(
        "fundamentals.example.v1",
        mapping,
        required=("instrument", "available_time", "value"),
        availability="point_in_time",
        revisions="versioned",
        timezone="UTC",
        timezone_columns=("available_time",),
        identifier_policy="vendor security ID as published",
    )
    mapping["value"] = "mutated"
    source = pl.DataFrame(
        {
            "ticker": ["A"],
            "published_at": [datetime(2026, 1, 1, tzinfo=UTC)],
            "revision": [1],
            "metric": [10.0],
        }
    ).lazy()

    result = adapt_vendor(source, schema)

    assert result.lazy is True
    assert result.columns == ("instrument", "available_time", "revision_id", "value")
    assert schema.columns["value"] == "metric"
    assert result.evidence.metadata.parameters["availability"] == "point_in_time"
    assert result.evidence.warnings


def test_vendor_schema_rejects_unsubstantiated_temporal_contracts() -> None:
    with pytest.raises(MethodContractError, match="available_time"):
        VendorSchema(
            "bad",
            {"value": "metric"},
            required=("value",),
            availability="point_in_time",
        )
    with pytest.raises(MethodContractError, match="revision_time or revision_id"):
        VendorSchema(
            "bad",
            {"value": "metric"},
            required=("value",),
            revisions="versioned",
        )


def test_vendor_adapter_rejects_timezone_mismatch_and_column_collision() -> None:
    timezone_schema = VendorSchema(
        "tz",
        {"available_time": "published_at"},
        required=("available_time",),
        availability="point_in_time",
        timezone="UTC",
        timezone_columns=("available_time",),
    )
    with pytest.raises(DataContractError, match="timezone-aware"):
        adapt_vendor(pl.DataFrame({"published_at": [datetime(2026, 1, 1)]}), timezone_schema)

    collision_schema = VendorSchema(
        "collision",
        {"value": "metric"},
        required=("value",),
    )
    with pytest.raises(DataContractError, match="overwrite"):
        adapt_vendor(pl.DataFrame({"value": [1.0], "metric": [2.0]}), collision_schema)


def test_backtest_adapter_requires_and_records_complete_semantics() -> None:
    schema = BacktestSchema(
        "engine.daily-returns.v1",
        "returns",
        {"time": "date", "strategy": "model", "return": "pnl_return"},
        _semantics(),
    )
    source = pl.DataFrame({"date": [1, 2], "model": ["alpha", "alpha"], "pnl_return": [0.1, -0.05]})

    result = adapt_backtest(source, schema, collect=True)

    assert result.columns == ("time", "strategy", "return")
    assert result.evidence.metadata.parameters["methodology_executed"] is False
    semantics = result.evidence.metadata.parameters["semantics"]
    assert isinstance(semantics, Mapping)
    assert semantics["returns"] == "net"
    assert semantics["execution_delay"] == "one session"


def test_backtest_schema_rejects_ambiguous_fields_and_semantics() -> None:
    with pytest.raises(MethodContractError, match="missing canonical mappings"):
        BacktestSchema(
            "missing",
            "returns",
            {"time": "date", "return": "value"},
            _semantics(),
        )
    with pytest.raises(MethodContractError, match="must not be empty"):
        BacktestSemantics(
            returns="gross",
            return_frequency="",
            compounding="simple",
            position_timing="close",
            execution_delay="none",
            price_field="close",
            price_adjustment="raw",
            costs="excluded",
            borrow="not_applicable",
            timezone="UTC",
            calendar="24/7",
            session="continuous",
            missing_instruments="fail",
            delistings="fail",
        )


def test_sklearn_adapter_freezes_walk_forward_folds_and_validates_shapes() -> None:
    intervals = pl.DataFrame({"time": list(range(8)), "feature": np.arange(8.0)})
    adapter = as_sklearn_cv(WalkForward(train=3, test=2, step=2), intervals)

    assert isinstance(adapter, SklearnCV)
    assert adapter.get_n_splits() == 2
    observed = list(adapter.split(np.arange(8.0), np.arange(8.0)))
    assert [item[0].tolist() for item in observed] == [[0, 1, 2], [0, 1, 2, 3, 4]]
    assert [item[1].tolist() for item in observed] == [[3, 4], [5, 6]]
    assert repr(adapter) == "SklearnCV(n_splits=2, n_samples=8)"
    with pytest.raises(DataContractError, match="X row count"):
        list(adapter.split(np.arange(7.0)))
    with pytest.raises(MethodContractError, match="groups are not consumed"):
        adapter.get_n_splits(groups=np.zeros(8))


def test_sklearn_adapter_supports_purged_interval_splitters() -> None:
    intervals = pl.DataFrame(
        {
            "observation_time": list(range(6)),
            "label_start": list(range(6)),
            "label_end": [value + 1 for value in range(6)],
        }
    )
    adapter = SklearnCV(PurgedKFold(n_splits=3), intervals)
    assert adapter.get_n_splits(np.zeros((6, 1))) == 3
    assert len(list(adapter.split(np.zeros((6, 1))))) == 3


def test_sklearn_adapter_rejects_unsupported_splitters() -> None:
    with pytest.raises(MethodContractError, match="splitter must be"):
        SklearnCV(object(), pl.DataFrame({"time": [1]}))  # type: ignore[arg-type]
