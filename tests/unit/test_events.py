from __future__ import annotations

import polars as pl
import pytest

from lacuna.events import event_response, event_windows
from lacuna.exceptions import DataContractError
from lacuna.types import FindingState


def _prices(*, instruments: tuple[str, ...] = ("A",), periods: int = 30) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "time": [time for instrument in instruments for time in range(periods)],
            "instrument": [instrument for instrument in instruments for _ in range(periods)],
            "close": [
                100.0 + time * (index + 1)
                for index, _instrument in enumerate(instruments)
                for time in range(periods)
            ],
        }
    )


def test_event_windows_anchor_on_availability_and_use_exact_offsets() -> None:
    events = pl.DataFrame(
        {
            "event_id": ["e1"],
            "instrument": ["A"],
            "event_time": [5],
            "available_time": [7],
        }
    )
    result = event_windows(
        events,
        _prices(),
        before=2,
        after=2,
        price_adjustment="split_adjusted",
    )
    frame = result.frame

    assert frame.get_column("offset").to_list() == [-2, -1, 0, 1, 2]
    anchor_row = frame.filter(pl.col("offset") == 0).row(0, named=True)
    assert anchor_row["anchor_time"] == 7
    assert anchor_row["aligned_anchor_time"] == 7
    assert anchor_row["price_time"] == 7
    assert anchor_row["response"] == 0.0
    assert result.metadata.parameters["offset_interval"] == (-2, 3)
    assert result.evidence.table("data_attrition")[-1]["excluded_rows"] == 0


def test_retrospective_event_time_anchor_records_lookahead() -> None:
    events = pl.DataFrame(
        {
            "event_id": ["e1"],
            "instrument": ["A"],
            "event_time": [5],
            "available_time": [7],
        }
    )
    result = event_windows(
        events,
        _prices(),
        anchor="event_time",
        before=1,
        after=1,
    )
    assert result.frame.filter(pl.col("offset") == 0).get_column("price_time")[0] == 5
    assert "EVENT_RETROSPECTIVE_ANCHOR_LOOKAHEAD" in {
        finding.code for finding in result.evidence.findings
    }


def test_event_windows_make_censoring_and_missing_prices_visible() -> None:
    events = pl.DataFrame(
        {
            "event_id": ["early"],
            "instrument": ["A"],
            "event_time": [1],
            "available_time": [1],
        }
    )
    prices = _prices().with_columns(
        pl.when(pl.col("time") == 2).then(None).otherwise(pl.col("close")).alias("close")
    )
    result = event_windows(events, prices, before=3, after=2)
    coverage = result.evidence.table("event_coverage")[0]

    assert coverage["left_censored_rows"] == 2
    assert coverage["missing_price_rows"] == 1
    assert coverage["observed_rows"] == 3
    assert result.evidence.metrics["censored_events"] == 1


def test_duplicate_and_overlapping_events_raise_unless_retained() -> None:
    duplicate = pl.DataFrame(
        {
            "event_id": ["same", "same"],
            "instrument": ["A", "A"],
            "event_time": [5, 10],
            "available_time": [5, 10],
        }
    )
    with pytest.raises(DataContractError, match="duplicate rows"):
        event_windows(duplicate, _prices(), before=1, after=1)

    overlapping = duplicate.with_columns(pl.Series("event_id", ["one", "two"])).with_columns(
        pl.Series("event_time", [5, 6]),
        pl.Series("available_time", [5, 6]),
    )
    with pytest.raises(DataContractError, match="overlapping"):
        event_windows(overlapping, _prices(), before=1, after=1)

    retained = event_windows(
        overlapping,
        _prices(),
        before=1,
        after=1,
        overlap_policy="keep",
    )
    assert retained.frame.get_column("overlap_cluster").n_unique() == 1
    assert retained.evidence.metrics["overlapping_events"] == 2


def _many_windows(*, clusters: int = 20) -> object:
    instruments = tuple(f"asset-{index}" for index in range(clusters))
    events = pl.DataFrame(
        {
            "event_id": [f"event-{index}" for index in range(clusters)],
            "instrument": list(instruments),
            "event_time": [index + 2 for index in range(clusters)],
            "available_time": [index + 2 for index in range(clusters)],
        }
    )
    return event_windows(
        events,
        _prices(instruments=instruments, periods=clusters + 5),
        before=1,
        after=2,
        price_adjustment="split_adjusted",
    )


def test_event_response_requires_cluster_support_for_inference() -> None:
    result = event_response(_many_windows(clusters=5), resamples=100, seed=2)
    assert result.findings[0].state == FindingState.UNKNOWN
    assert result.metrics["successful_resamples"] == 0
    assert all(row["pointwise_lower"] is None for row in result.table("event_response"))


def test_event_response_is_deterministic_and_has_simultaneous_bands() -> None:
    windows = _many_windows(clusters=20)
    first = event_response(windows, resamples=100, seed=19)
    second = event_response(windows, resamples=100, seed=19)

    assert first.metrics == second.metrics
    assert first.tables == second.tables
    assert first.metadata.parameters["root_entropy"] == 19
    assert first.metrics["n_clusters"] == 20
    assert first.findings[0].state == FindingState.PASS
    rows = first.table("event_response")
    assert [row["offset"] for row in rows] == [-1, 0, 1, 2]
    assert any(row["simultaneous_lower"] is not None for row in rows)
    for row in rows:
        if row["simultaneous_lower"] is not None:
            assert row["simultaneous_lower"] <= row["inference_mean"]
            assert row["simultaneous_upper"] >= row["inference_mean"]


def test_event_response_zero_variance_has_no_standardized_band() -> None:
    clusters = 20
    instruments = tuple(f"asset-{index}" for index in range(clusters))
    events = pl.DataFrame(
        {
            "event_id": [f"event-{index}" for index in range(clusters)],
            "instrument": list(instruments),
            "event_time": [index + 2 for index in range(clusters)],
            "available_time": [index + 2 for index in range(clusters)],
        }
    )
    prices = pl.DataFrame(
        {
            "time": [time for instrument in instruments for time in range(clusters + 5)],
            "instrument": [instrument for instrument in instruments for _ in range(clusters + 5)],
            "close": [
                100.0 * 1.01**time for _instrument in instruments for time in range(clusters + 5)
            ],
        }
    )
    windows = event_windows(events, prices, before=1, after=1)
    result = event_response(windows, resamples=100, seed=11)

    assert result.metrics["simultaneous_critical_value"] is None
    assert all(row["simultaneous_lower"] is None for row in result.table("event_response"))
