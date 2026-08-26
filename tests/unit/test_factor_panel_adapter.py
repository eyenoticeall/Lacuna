from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import polars as pl
import pytest

from lacuna.adapters import (
    FactorPanelSchema,
    FactorPanelSemantics,
    adapt_factor_panel,
)
from lacuna.exceptions import DataContractError, MethodContractError
from lacuna.signal import ic

FIXTURE = Path(__file__).parents[1] / "fixtures" / "alphalens-reloaded-f0a07c22.json"


def _semantics(**overrides: str) -> FactorPanelSemantics:
    values = {
        "signal_observation": "end_of_session",
        "decision_time_rule": "next_session_open",
        "forward_return_entry": "next_session_open",
        "forward_return_exit": "one_trading_observation_after_entry",
        "horizon_clock": "trading_observations",
        "timezone": "UTC",
        "calendar": "fixture_sessions",
        "adjustment_policy": "total_return_adjusted",
        "group_availability": "unknown",
        "imported_bucket_definition": "not_applicable",
    }
    values.update(overrides)
    return FactorPanelSemantics(**values)


def _schema(**columns: str) -> FactorPanelSchema:
    mapping = {
        "observation_time": "date",
        "instrument": "asset",
        "signal": "factor",
    }
    mapping.update(columns)
    return FactorPanelSchema(
        schema_id="factor-panel-test",
        columns=mapping,
        semantics=_semantics(),
    )


def test_eager_and_lazy_polars_preserve_order_extras_and_laziness() -> None:
    source = pl.DataFrame(
        {
            "date": [2, 1],
            "asset": ["B", "A"],
            "factor": [0.2, 0.1],
            "vendor_note": ["second", "first"],
        }
    )

    eager = adapt_factor_panel(source, _schema())
    lazy = adapt_factor_panel(source.lazy(), _schema())
    collected = adapt_factor_panel(source.lazy(), _schema(), collect=True)

    assert cast(pl.DataFrame, eager.frame).rows() == [
        (2, "B", 0.2, "second"),
        (1, "A", 0.1, "first"),
    ]
    assert eager.columns == ("observation_time", "instrument", "signal", "vendor_note")
    assert lazy.lazy is True
    assert collected.lazy is False
    assert lazy.evidence.metadata.parameters["methodology_executed"] is False
    assert collected.evidence.metadata.parameters["adapter_copy"] == "materializing"


def test_named_pandas_multiindex_is_used_only_through_explicit_mapping() -> None:
    pd = pytest.importorskip("pandas")
    source = pd.DataFrame(
        {"factor": [0.1, 0.2], "1D": [0.01, 0.02], "extra": ["x", "y"]},
        index=pd.MultiIndex.from_tuples(
            [("2024-01-01", "A"), ("2024-01-01", "B")],
            names=["date", "asset"],
        ),
    )
    result = adapt_factor_panel(source, _schema(forward_return="1D"))

    assert result.columns == (
        "observation_time",
        "instrument",
        "signal",
        "forward_return",
        "extra",
    )
    assert result.evidence.metadata.parameters["mapped_pandas_index_levels"] == (
        "date",
        "asset",
    )

    with pytest.raises(DataContractError, match="missing required columns"):
        adapt_factor_panel(
            source,
            FactorPanelSchema(
                schema_id="no-index-inference",
                columns={
                    "observation_time": "timestamp_column",
                    "instrument": "instrument_column",
                    "signal": "factor",
                },
                semantics=_semantics(),
            ),
        )


def test_arrow_chunking_and_dtypes_are_preserved_without_methodology() -> None:
    pa = pytest.importorskip("pyarrow")
    source = pa.table(
        {
            "date": pa.chunked_array([[1], [2]]),
            "asset": pa.chunked_array([["A"], ["B"]]),
            "factor": pa.chunked_array([[0.1], [0.2]]),
            "bucket_source": pa.chunked_array([[1], [2]], type=pa.int16()),
        }
    )
    result = adapt_factor_panel(source, _schema(bucket="bucket_source"))
    frame = cast(pl.DataFrame, result.frame)

    assert frame.schema["signal"] == pl.Float64
    assert frame.schema["bucket"] == pl.Int16
    assert result.evidence.metadata.parameters["methodology_executed"] is False
    assert result.evidence.metadata.parameters["adapter_copy"] == "potentially_zero_copy"


def test_mapping_validation_rejects_duplicates_unknown_fields_and_bad_dtypes() -> None:
    with pytest.raises(MethodContractError, match="map uniquely"):
        FactorPanelSchema(
            schema_id="duplicate",
            columns={
                "observation_time": "x",
                "instrument": "x",
                "signal": "factor",
            },
            semantics=_semantics(),
        )
    with pytest.raises(MethodContractError, match="unsupported"):
        FactorPanelSchema(
            schema_id="unknown",
            columns={
                "observation_time": "date",
                "instrument": "asset",
                "signal": "factor",
                "magic": "hidden_method",
            },
            semantics=_semantics(),
        )
    with pytest.raises(DataContractError, match="signal must use a numeric dtype"):
        adapt_factor_panel(
            pl.DataFrame({"date": [1], "asset": ["A"], "factor": ["high"]}),
            _schema(),
        )


def test_unknown_semantics_remain_unknown_and_are_serializable() -> None:
    schema = FactorPanelSchema(
        schema_id="unknown-timing",
        columns={
            "observation_time": "date",
            "instrument": "asset",
            "signal": "factor",
            "group": "sector",
        },
        semantics=_semantics(
            decision_time_rule="unknown",
            group_availability="unknown",
        ),
    )
    result = adapt_factor_panel(
        pl.DataFrame({"date": [1], "asset": ["A"], "factor": [0.2], "sector": ["X"]}),
        schema,
    )

    assert result.evidence.findings[0].state.value == "UNKNOWN"
    assert result.evidence.metrics["unknown_semantics"] == 2
    assert "NaN" not in result.evidence.to_json()


def test_pinned_alphalens_ic_fixture_matches_only_under_declared_semantics() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    panel = pl.DataFrame(fixture["panel"]).with_columns(
        pl.col("date").str.to_date(),
        pl.lit("1D").alias("horizon"),
    )
    adapted = adapt_factor_panel(
        panel,
        FactorPanelSchema(
            schema_id="alphalens-reloaded-f0a07c22-ic",
            columns={
                "observation_time": "date",
                "instrument": "asset",
                "signal": "factor",
                "forward_return": "1D",
                "horizon": "horizon",
                "group": "group",
            },
            semantics=_semantics(
                signal_observation="fixture_date",
                decision_time_rule="fixture_compatible_same_index",
                forward_return_entry="fixture_precomputed",
                forward_return_exit="fixture_precomputed_1D",
                group_availability="fixture_static",
            ),
        ),
    )
    result = ic(
        adapted.frame,
        adapted.frame,
        signal_time="observation_time",
        label_time="observation_time",
        by=("observation_time", "horizon"),
        use_native=False,
    )
    grouped = ic(
        adapted.frame,
        adapted.frame,
        signal_time="observation_time",
        label_time="observation_time",
        by=("observation_time", "horizon", "group"),
        min_observations=2,
        use_native=False,
    )

    assert [row["ic"] for row in result.table("ic_by_period")] == fixture["expected"][
        "ic_by_period"
    ]
    assert [row["ic"] for row in grouped.table("ic_by_period")] == fixture["expected"][
        "grouped_ic_by_period"
    ]
