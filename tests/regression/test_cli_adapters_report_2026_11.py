"""Regression tests for CLI and adapter defects reported against v0.14.1."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import polars as pl
import pytest

from lacuna.adapters import (
    BacktestSchema,
    BacktestSemantics,
    FactorPanelSchema,
    FactorPanelSemantics,
    VendorSchema,
    adapt_backtest,
    adapt_factor_panel,
    adapt_vendor,
    from_duckdb,
)
from lacuna.cli import _parser, _scan_frame, main
from lacuna.exceptions import DataContractError, MethodContractError

_START = dt.date(2020, 1, 1)


def _dated_inputs(root: Path, *, text_ids: bool = False) -> tuple[Path, Path]:
    periods, instruments = 14, 6
    names = [f"2020-01-0{index + 1}" if text_ids else f"asset-{index}" for index in range(6)]
    signal_rows = [
        (_START + dt.timedelta(days=t), names[i], float(i))
        for t in range(periods - 2)
        for i in range(instruments)
    ]
    price_rows = [
        (_START + dt.timedelta(days=t), names[i], 100.0 * (1.0 + 0.002 * (i + 1)) ** t)
        for i in range(instruments)
        for t in range(periods)
    ]
    signal = pl.DataFrame(signal_rows, schema=["time", "instrument", "signal"], orient="row")
    prices = pl.DataFrame(price_rows, schema=["time", "instrument", "close"], orient="row")
    signal_path, price_path = root / "signal.csv", root / "prices.csv"
    signal.with_columns(pl.col("time").cast(pl.String)).write_csv(signal_path)
    prices.with_columns(pl.col("time").cast(pl.String)).write_csv(price_path)
    return signal_path, price_path


def _run_signal(signal: Path, prices: Path, *extra: str) -> list[str]:
    return [
        "signal",
        "--signal",
        str(signal),
        "--prices",
        str(prices),
        "--horizon",
        "1D",
        "--quantiles",
        "3",
        "--bootstrap-resamples",
        "100",
        "--seed",
        "9",
        "--no-native",
        "--format",
        "json",
        *extra,
    ]


# --- 1. dated CSV --------------------------------------------------------------------------


def test_signal_cli_reads_csv_with_iso_date_time_column(tmp_path: Path, capsys: object) -> None:
    """The CLI advertises CSV input, so an ISO-date time column must be parsed, not rejected."""

    signal, prices = _dated_inputs(tmp_path)
    exit_code = main(_run_signal(signal, prices))
    captured = capsys.readouterr()  # type: ignore[attr-defined]

    assert exit_code == 0, captured.err
    assert json.loads(captured.out)["metadata"]["method"] == "audit.v0_1"


def test_csv_scan_parses_only_the_declared_time_column(tmp_path: Path) -> None:
    """Date-looking instrument identifiers must keep their inferred text type."""

    signal, _ = _dated_inputs(tmp_path, text_ids=True)
    schema = _scan_frame(str(signal), ("time",)).collect_schema()

    assert schema["time"] == pl.Date
    assert schema["instrument"] == pl.String
    assert schema["signal"] == pl.Float64


def test_csv_scan_does_not_reinterpret_columns_when_time_is_numeric(tmp_path: Path) -> None:
    path = tmp_path / "numeric.csv"
    path.write_text("time,instrument,signal\n1,2020-01-01,0.5\n2,2020-01-02,0.7\n")
    schema = _scan_frame(str(path), ("time",)).collect_schema()

    assert schema["time"] == pl.Int64
    assert schema["instrument"] == pl.String


def test_csv_scan_parses_iso_datetimes_with_offsets(tmp_path: Path) -> None:
    path = tmp_path / "stamps.csv"
    path.write_text("time,instrument\n2020-01-01T09:30:00+00:00,A\n2020-01-02T09:30:00+00:00,A\n")
    frame = _scan_frame(str(path), ("time",)).collect()

    assert isinstance(frame.schema["time"], pl.Datetime)
    assert frame.schema["time"].time_zone == "UTC"  # type: ignore[union-attr]


def test_csv_scan_rejects_unparseable_time_with_a_lacuna_contract_error(tmp_path: Path) -> None:
    """Unparseable time text must raise DataContractError, never a raw Polars error."""

    path = tmp_path / "bad.csv"
    path.write_text("time,instrument\n2020-01-01,A\nnot-a-date,A\n")
    with pytest.raises(DataContractError, match="could not be parsed as ISO 8601"):
        _scan_frame(str(path), ("time",))


def test_signal_cli_reports_unparseable_csv_time_as_a_clean_error(
    tmp_path: Path, capsys: object
) -> None:
    signal, prices = _dated_inputs(tmp_path)
    signal.write_text(signal.read_text().replace("2020-01-03", "03/01/2020"))
    exit_code = main(_run_signal(signal, prices))
    captured = capsys.readouterr()  # type: ignore[attr-defined]

    assert exit_code == 1
    assert "could not be parsed as ISO 8601" in captured.err


# --- 2. --no-color -------------------------------------------------------------------------


def test_no_color_flag_is_documented_as_a_no_op_and_output_is_never_colored(
    tmp_path: Path, capsys: object
) -> None:
    """``--no-color`` was advertised as disabling color that never existed."""

    parser = _parser()
    for command in ("signal", "audit"):
        subparser = next(
            action.choices[command]  # type: ignore[attr-defined]
            for action in parser._actions
            if getattr(action, "choices", None) and command in action.choices
        )
        option = next(a for a in subparser._actions if "--no-color" in a.option_strings)
        assert option.help is not None
        assert "no effect" in option.help
        assert "disable terminal color" not in option.help

    signal, prices = _dated_inputs(tmp_path)
    for extra in ((), ("--no-color",)):
        assert main(_run_signal(signal, prices, *extra)) == 0
        assert "\x1b[" not in capsys.readouterr().out  # type: ignore[attr-defined]


# --- 3. optional mapped columns ------------------------------------------------------------


def _vendor(**overrides: object) -> VendorSchema:
    values: dict[str, object] = {
        "schema_id": "vendor.test",
        "columns": {"time": "ts", "value": "val", "note": "memo"},
        "required": ("time", "value"),
    }
    values.update(overrides)
    return VendorSchema(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("lazy", [False, True])
def test_vendor_optional_mapped_column_absent_from_data_is_skipped_and_recorded(
    lazy: bool,
) -> None:
    """A mapped-but-not-required column absent from the data must not raise a Polars error."""

    data: pl.DataFrame | pl.LazyFrame = pl.DataFrame({"ts": [1, 2], "val": [0.1, 0.2]})
    result = adapt_vendor(data.lazy() if lazy else data, _vendor())

    assert result.columns == ("time", "value")
    assert result.evidence.metadata.parameters["absent_optional_columns"] == ("note",)


def test_vendor_optional_mapped_column_present_is_renamed_and_not_reported_absent() -> None:
    data = pl.DataFrame({"ts": [1], "val": [0.1], "memo": ["x"]})
    result = adapt_vendor(data, _vendor())

    assert result.columns == ("time", "value", "note")
    assert result.evidence.metadata.parameters["absent_optional_columns"] == ()


def test_absent_optional_mapping_still_rejects_unrelated_column_with_canonical_name() -> None:
    """Skipping an absent optional source must not let an unrelated ``note`` column pose as it."""

    data = pl.DataFrame({"ts": [1], "val": [0.1], "note": ["unrelated"]})
    with pytest.raises(DataContractError, match="overwrite existing columns: note"):
        adapt_vendor(data, _vendor())


def test_vendor_point_in_time_schema_rejects_absent_available_time_source() -> None:
    """PIT safety cannot be claimed when the mapped availability column is missing."""

    schema = _vendor(
        columns={"time": "ts", "value": "val", "available_time": "avail"},
        availability="point_in_time",
    )
    with pytest.raises(DataContractError, match="available_time"):
        adapt_vendor(pl.DataFrame({"ts": [1], "val": [0.1]}), schema)


def test_vendor_versioned_schema_rejects_when_all_revision_sources_absent() -> None:
    schema = _vendor(
        columns={"time": "ts", "value": "val", "revision_id": "rev"},
        revisions="versioned",
    )
    with pytest.raises(DataContractError, match="revision"):
        adapt_vendor(pl.DataFrame({"ts": [1], "val": [0.1]}), schema)


def test_vendor_absent_optional_timezone_column_is_skipped_without_keyerror() -> None:
    schema = _vendor(
        columns={"time": "ts", "value": "val", "seen": "seen_at"},
        timezone="UTC",
        timezone_columns=("seen",),
    )
    result = adapt_vendor(pl.DataFrame({"ts": [1], "val": [0.1]}), schema)

    assert result.evidence.metadata.parameters["absent_optional_columns"] == ("seen",)


def test_backtest_optional_mapped_column_absent_from_data_is_skipped_and_recorded() -> None:
    semantics = BacktestSemantics(
        returns="net",
        return_frequency="daily",
        compounding="simple",
        position_timing="close-to-close",
        execution_delay="one session",
        price_field="close",
        price_adjustment="raw",
        costs="included",
        borrow="included",
        timezone="UTC",
        calendar="XNYS",
        session="regular",
        missing_instruments="retain as null",
        delistings="terminal return included",
    )
    schema = BacktestSchema(
        schema_id="bt.test",
        artifact="returns",
        columns={"time": "t", "strategy": "s", "return": "r", "memo": "m"},
        semantics=semantics,
    )
    result = adapt_backtest(pl.DataFrame({"t": [1], "s": ["a"], "r": [0.1]}), schema)

    assert result.columns == ("time", "strategy", "return")
    assert result.evidence.metadata.parameters["absent_optional_columns"] == ("memo",)


def test_factor_panel_absent_optional_column_is_recorded() -> None:
    semantics = FactorPanelSemantics(
        signal_observation="unknown",
        decision_time_rule="unknown",
        forward_return_entry="unknown",
        forward_return_exit="unknown",
        horizon_clock="unknown",
        timezone="unknown",
        calendar="unknown",
        adjustment_policy="unknown",
        group_availability="unknown",
        imported_bucket_definition="unknown",
    )
    schema = FactorPanelSchema(
        schema_id="fp.test",
        columns={
            "observation_time": "t",
            "instrument": "i",
            "signal": "s",
            "forward_return": "fwd",
        },
        semantics=semantics,
    )
    result = adapt_factor_panel(pl.DataFrame({"t": [1], "i": ["A"], "s": [0.5]}), schema)

    assert result.evidence.metadata.parameters["absent_optional_columns"] == ("forward_return",)


# --- 4. from_duckdb(collect=) --------------------------------------------------------------


class _Source:
    def __init__(self) -> None:
        self.calls: list[int] = []

    def to_arrow_reader(self, batch_size: int) -> object:
        self.calls.append(batch_size)
        return pl.DataFrame({"value": [1]})


def test_from_duckdb_rejects_collect_false_rather_than_silently_returning_eager_data() -> None:
    """``collect=False`` used to be ignored; eager materialization is inherent, so reject it."""

    source = _Source()
    with pytest.raises(MethodContractError, match="cannot defer collection"):
        from_duckdb(source, collect=False)
    assert source.calls == []


def test_from_duckdb_default_collect_returns_an_eager_frame() -> None:
    result = from_duckdb(_Source())
    assert result.lazy is False
    assert isinstance(result.frame, pl.DataFrame)


# --- 5. source_type spelling ---------------------------------------------------------------


def test_adapter_source_type_uses_the_public_polars_spelling() -> None:
    """Adapters recorded ``polars.dataframe.frame.DataFrame``; labels use ``polars.DataFrame``."""

    frame = pl.DataFrame({"ts": [1], "val": [0.1]})
    eager = adapt_vendor(frame, _vendor())
    lazy = adapt_vendor(frame.lazy(), _vendor())

    assert eager.evidence.metadata.parameters["source_type"] == "polars.DataFrame"
    assert lazy.evidence.metadata.parameters["source_type"] == "polars.LazyFrame"


def test_mixed_offset_and_naive_csv_times_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "mixed.csv"
    path.write_text("time,instrument\n2020-01-01T09:30:00+00:00,A\n2020-01-02T09:30:00,A\n")
    with pytest.raises(DataContractError, match="all values with or all without"):
        _scan_frame(str(path), ("time",))
