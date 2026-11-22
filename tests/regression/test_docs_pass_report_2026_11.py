"""Regression tests for defects the website documentation pass reported against v0.14.2."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import polars as pl
import pytest

import lacuna as lc
from lacuna.bias import asof_join, future_data_check, revision_diagnostics
from lacuna.cli import _scan_frame
from lacuna.cv import PurgedKFold
from lacuna.labels import forward_returns
from lacuna.signal import BucketSpec, bucket_returns, bucketize, ic, quantiles
from lacuna.types import FindingState


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


# --- headline counts ---------------------------------------------------------------------


def test_bucket_and_quantile_observation_counts_describe_the_headline_horizon_only() -> None:
    """``n_observations`` sits beside single-horizon headline metrics and must not pool.

    Method version 2 reported the row count of every horizon next to a spread and a
    monotonicity that describe only ``headline_horizon``.
    """

    signal, prices = _panel()
    labels = forward_returns(prices, horizons=("1D", "5D"), price_adjustment="raw")
    per_horizon = {
        row["horizon"]: row["len"] for row in labels.frame.group_by("horizon").len().to_dicts()
    }
    assert per_horizon["1D"] != per_horizon["5D"]

    quantile_result = quantiles(signal, labels, quantiles=3)
    bucketed = bucketize(signal, spec=BucketSpec.quantiles(3), by="time")
    bucket_result = bucket_returns(bucketed, labels)

    for result in (quantile_result, bucket_result):
        assert result.metadata.method_version == 3
        assert result.metadata.parameters["headline_horizon"] == "1D"
        assert result.metrics["n_observations"] == per_horizon["1D"]
        # The join diagnostics still describe every matched row, as they do for ``ic``.
        assert result.metrics["matched_rows_before_policy"] == sum(per_horizon.values())
    assert quantile_result.metrics["n_observations"] == ic(signal, labels).metrics["n_observations"]


def test_observation_count_is_null_when_the_headline_horizon_is_undeclared() -> None:
    signal, prices = _panel()
    labels = forward_returns(prices, horizons=("1D", "5D"), price_adjustment="raw")

    result = quantiles(signal, labels.frame, quantiles=3)

    assert "QUANTILE_HEADLINE_HORIZON_UNDECLARED" in {f.code for f in result.findings}
    assert result.metrics["n_observations"] is None


def test_quantiles_names_its_empty_headline_finding_as_a_quantile_finding() -> None:
    """``quantiles`` renames its other bucket findings; the empty-headline one leaked through."""

    signal, prices = _panel(n_times=60)
    late = signal.filter(pl.col("time") >= 50)
    labels = forward_returns(prices, horizons=("20D", "1D"), price_adjustment="raw")

    result = quantiles(late, labels, quantiles=3)
    codes = {finding.code for finding in result.findings}

    assert "QUANTILE_HEADLINE_HORIZON_EMPTY" in codes
    assert "BUCKET_HEADLINE_HORIZON_EMPTY" not in codes
    empty = next(f for f in result.findings if f.code == "QUANTILE_HEADLINE_HORIZON_EMPTY")
    assert empty.state == FindingState.UNKNOWN
    assert empty.evidence["headline_horizon"] == "20D"
    assert result.metrics["n_observations"] == 0


# --- bare Lacuna label frames --------------------------------------------------------------


def test_bare_lacuna_label_frame_works_with_a_renamed_signal_identifier() -> None:
    """``forward_returns`` writes ``instrument`` whatever the source column was called.

    Passing ``labels.frame`` with ``instrument="ticker"`` raised ``missing required columns:
    ticker`` although the same call with the ``LabelResult`` worked.
    """

    signal, prices = _panel()
    signal = signal.rename({"instrument": "ticker"})
    prices = prices.rename({"instrument": "ticker"})
    labels = forward_returns(prices, horizon="5D", instrument="ticker", price_adjustment="raw")
    assert "ticker" not in labels.frame.columns

    from_result = ic(signal, labels, instrument="ticker", use_native=False)
    from_frame = ic(signal, labels.frame, instrument="ticker", use_native=False)

    assert from_frame.metrics == from_result.metrics
    assert from_frame.table("ic_by_period") == from_result.table("ic_by_period")
    operations = from_frame.metadata.parameters["label_input"]["execution_operations"]  # type: ignore[index,call-overload]
    assert "canonical_label_instrument" in operations
    assert (
        quantiles(signal, labels.frame, instrument="ticker", quantiles=3).metrics
        == quantiles(signal, labels, instrument="ticker", quantiles=3).metrics
    )


def test_caller_named_label_instrument_column_wins_over_the_canonical_one() -> None:
    """A caller-built frame that has the declared column is read with it, never by fallback."""

    signal, prices = _panel()
    labels = forward_returns(prices, horizon="5D", price_adjustment="raw")
    signal = signal.rename({"instrument": "ticker"})
    both = labels.frame.rename({"instrument": "ticker"}).with_columns(
        pl.lit("not-an-instrument").alias("instrument")
    )

    result = ic(signal, both, instrument="ticker", use_native=False)

    assert (
        result.metrics["mean_ic"]
        == ic(signal.rename({"ticker": "instrument"}), labels, use_native=False).metrics["mean_ic"]
    )
    operations = result.metadata.parameters["label_input"]["execution_operations"]  # type: ignore[index,call-overload]
    assert "canonical_label_instrument" not in operations


def test_label_frame_without_any_instrument_column_still_names_the_declared_one() -> None:
    signal, prices = _panel()
    labels = forward_returns(prices, horizon="5D", price_adjustment="raw")
    signal = signal.rename({"instrument": "ticker"})

    with pytest.raises(lc.DataContractError, match="missing required columns: ticker"):
        ic(signal, labels.frame.drop("instrument"), instrument="ticker", use_native=False)


# --- forward_returns missing="raise" with delisting returns ---------------------------------


def _delisting_prices() -> pl.DataFrame:
    _, prices = _panel(n_times=12, n_instruments=3)
    prices = prices.with_columns(pl.lit(None, dtype=pl.Float64).alias("delisting_return"))
    terminal = (pl.col("instrument") == "I0") & (pl.col("time") == 8)
    return prices.filter(~((pl.col("instrument") == "I0") & (pl.col("time") > 8))).with_columns(
        pl.when(terminal).then(None).otherwise(pl.col("close")).alias("close"),
        pl.when(terminal)
        .then(-0.3)
        .otherwise(pl.col("delisting_return"))
        .alias("delisting_return"),
    )


def test_missing_raise_accepts_the_terminal_row_that_delisting_return_handles() -> None:
    """A null exit price with a declared delisting return is handled, not missing.

    ``missing="raise"`` rejected that row, so the policy could not be combined with
    ``delisting_return`` at all.
    """

    prices = _delisting_prices()
    kwargs = {"horizon": "1D", "delisting_return": "delisting_return", "price_adjustment": "raw"}

    raised = forward_returns(prices, missing="raise", **kwargs)  # type: ignore[arg-type]
    dropped = forward_returns(prices, missing="drop", **kwargs)  # type: ignore[arg-type]

    assert raised.frame.equals(dropped.frame)
    terminal = raised.frame.filter((pl.col("instrument") == "I0") & (pl.col("label_end") == 8))
    assert terminal.get_column("forward_return").to_list() == [-0.3]


def test_missing_raise_still_rejects_null_prices_without_a_delisting_return() -> None:
    prices = _delisting_prices().with_columns(
        pl.when((pl.col("instrument") == "I1") & (pl.col("time") == 4))
        .then(None)
        .otherwise(pl.col("close"))
        .alias("close")
    )

    with pytest.raises(lc.DataContractError, match="prices contain 1 rows with null or NaN"):
        forward_returns(
            prices,
            horizon="1D",
            delisting_return="delisting_return",
            price_adjustment="raw",
            missing="raise",
        )
    with pytest.raises(lc.DataContractError, match="prices contain 2 rows with null or NaN"):
        forward_returns(prices, horizon="1D", price_adjustment="raw", missing="raise")


# --- audit inference_horizon policy ---------------------------------------------------------


def test_integer_inference_horizon_policy_reads_the_same_horizon_as_its_label() -> None:
    """``lc.audit`` accepted an integer horizon and then matched it against nothing.

    Horizon labels are strings such as ``"5D"``. An integer made the horizon rules
    ``UNKNOWN`` and kept the zero-purge warning from firing, while ``SignalStudy.audit``
    already read integer N as ``"ND"``.
    """

    signal, prices = _panel(n_times=80)
    labels = forward_returns(prices, horizons=("1D", "5D"), price_adjustment="raw")
    split = PurgedKFold(n_splits=3, use_native=False).split(
        labels.frame.filter(pl.col("horizon") == "1D")
    )
    assert split.evidence.metrics["purged_observations"] == 0
    results = {
        "ic": ic(signal, labels, use_native=False),
        "quantiles": quantiles(signal, labels, quantiles=3),
        "split": split.evidence,
    }

    def states(horizon: object) -> dict[str, FindingState]:
        report = lc.audit(results=results, policies={"inference_horizon": horizon})  # type: ignore[dict-item]
        return {finding.code: finding.state for finding in report.findings}

    by_integer, by_label = states(5), states("5D")

    assert by_integer == by_label
    assert by_integer["PURGED_VALIDATION_SUPPLIED"] == FindingState.WARN
    assert by_integer["IC_DEFINED"] != FindingState.UNKNOWN
    assert by_integer["QUANTILE_MONOTONICITY"] != FindingState.UNKNOWN
    # A horizon that names no row stays unknown; the integer form is not a wildcard.
    assert states(7)["IC_DEFINED"] == FindingState.UNKNOWN


# --- CLI CSV time parsing -------------------------------------------------------------------


@pytest.mark.parametrize("text", ["02/01/2025", "13/01/2025", "2025-1-2T03:04:05", "Jan 2 2025"])
def test_csv_time_text_that_is_not_iso_8601_is_rejected(tmp_path: Path, text: str) -> None:
    """Slash dates were parsed day-first by format inference instead of being rejected.

    ``02/01/2025`` became 2 January, so a month-first file was misdated without an error.
    """

    path = tmp_path / "times.csv"
    path.write_text(f"time,instrument\n{text},A\n{text},B\n")

    with pytest.raises(lc.DataContractError, match="could not be parsed as ISO 8601"):
        _scan_frame(str(path), ("time",))


@pytest.mark.parametrize(
    ("text", "time_zone"),
    [
        ("2025-01-02T03:04:05", None),
        ("2025-01-02 03:04:05", None),
        ("2025-01-02T03:04", None),
        ("2025-01-02T03:04:05.123456", None),
        ("2025-01-02T03:04:05Z", "UTC"),
        ("2025-01-02T03:04:05+01:00", "UTC"),
        ("2025-01-02 03:04:05.5+0100", "UTC"),
    ],
)
def test_csv_iso_datetime_forms_stay_accepted(
    tmp_path: Path, text: str, time_zone: str | None
) -> None:
    path = tmp_path / "times.csv"
    path.write_text(f"time,instrument\n{text},A\n")

    dtype = _scan_frame(str(path), ("time",)).collect_schema()["time"]

    assert isinstance(dtype, pl.Datetime)
    assert dtype.time_zone == time_zone


# --- bias: versions, revisions, Duration ----------------------------------------------------


def _duration_frames() -> tuple[pl.DataFrame, pl.DataFrame]:
    left = pl.DataFrame(
        {
            "decision_time": [timedelta(days=1), timedelta(days=3), timedelta(days=10)],
            "instrument": ["A", "A", "A"],
        }
    )
    right = pl.DataFrame(
        {
            "available_time": [timedelta(0), timedelta(days=2)],
            "instrument": ["A", "A"],
            "value": [1.0, 2.0],
        }
    )
    return left, right


def test_asof_join_supports_duration_time_columns_as_documented() -> None:
    """The docstring lists Duration time; the evidence step failed casting it to String."""

    left, right = _duration_frames()

    result = asof_join(left, right)

    assert result.frame.get_column("value").to_list() == [1.0, 2.0, 2.0]
    assert result.evidence.metadata.method_version == 2
    sample = result.evidence.table("join_sample")[0]
    assert sample["decision_time"] == "P1D"  # type: ignore[index,call-overload]
    assert sample["available_time"] == "PT0S"  # type: ignore[index,call-overload]
    assert result.evidence.metrics["future_matches"] == 0

    for tolerance in (timedelta(days=1), "1d"):
        bounded = asof_join(left, right, tolerance=tolerance)
        assert bounded.frame.get_column("value").to_list() == [1.0, 2.0, None]
    with pytest.raises(lc.MethodContractError, match="numeric tolerance has no unit"):
        asof_join(left, right, tolerance=5)


def test_duration_evidence_text_does_not_depend_on_the_time_unit() -> None:
    left, right = _duration_frames()
    samples = []
    for unit in ("ms", "us", "ns"):
        cast = pl.Duration(unit)  # type: ignore[arg-type]
        result = asof_join(
            left.with_columns(pl.col("decision_time").cast(cast)),
            right.with_columns(pl.col("available_time").cast(cast)),
        )
        samples.append(result.evidence.table("join_sample"))

    assert samples[0] == samples[1] == samples[2]


def test_asof_join_and_revision_diagnostics_accept_a_duration_revision() -> None:
    left = pl.DataFrame({"decision_time": [1, 3], "instrument": ["A", "A"]})
    right = pl.DataFrame(
        {
            "available_time": [0, 0, 2],
            "effective_time": [0, 0, 0],
            "instrument": ["A", "A", "A"],
            "value": [1.0, 1.5, 2.0],
            "revision": [timedelta(0), timedelta(days=1), timedelta(days=2)],
        }
    )

    joined = asof_join(left, right, revision="revision")
    diagnostics = revision_diagnostics(right, revision="revision", source_mode="point_in_time")

    assert joined.frame.get_column("value").to_list() == [1.5, 2.0]
    assert diagnostics.metadata.method_version == 2
    assert diagnostics.metrics["revised_facts"] == 1
    assert "BIAS_REVISION_HISTORY_VALID" in {finding.code for finding in diagnostics.findings}


def test_future_data_check_reports_duration_times() -> None:
    frame = pl.DataFrame(
        {
            "decision_time": [timedelta(days=1), timedelta(days=2)],
            "available_time": [timedelta(days=2), timedelta(days=1)],
            "instrument": ["A", "A"],
        }
    )

    result = future_data_check(frame)

    rows = result.table("future_rows")
    assert rows[0]["available_time"] == "P2D"  # type: ignore[index,call-overload]


@pytest.mark.parametrize("dtype", [pl.String, pl.Categorical])
def test_revision_diagnostics_rejects_lexicographic_revisions(dtype: type[pl.DataType]) -> None:
    """String revisions sort ``"10"`` below ``"9"`` and produced a false order violation.

    Availability follows the numeric revision order here, yet the lexicographic sort
    reported ``BIAS_REVISION_ORDER_INVALID``. ``asof_join`` already rejects these dtypes.
    """

    frame = pl.DataFrame(
        {
            "instrument": ["A", "A"],
            "effective_time": [0, 0],
            "available_time": [1, 2],
            "revision_id": pl.Series(["9", "10"], dtype=dtype),
        }
    )

    with pytest.raises(lc.DataContractError, match="no declared version order"):
        revision_diagnostics(frame, source_mode="point_in_time")

    numeric = frame.with_columns(pl.col("revision_id").cast(pl.String).cast(pl.Int64))
    result = revision_diagnostics(numeric, source_mode="point_in_time")
    assert "BIAS_REVISION_ORDER_INVALID" not in {finding.code for finding in result.findings}
