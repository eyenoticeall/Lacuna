"""Regression tests for the 2026-11 events and decay review (reported against v0.14.1)."""

from __future__ import annotations

import json
import math

import numpy as np
import polars as pl
import pytest

from lacuna.events import EventWindowResult, event_response, event_windows
from lacuna.signal import fit_decay
from lacuna.types import AnalysisResult, FindingState, ResultMetadata

_WINDOW_CODES = (
    "EVENT_RETROSPECTIVE_ANCHOR_LOOKAHEAD",
    "EVENT_WINDOWS_OVERLAP",
    "EVENT_WINDOWS_CENSORED",
    "EVENT_PRICE_ADJUSTMENT_UNKNOWN",
)


def _prices(instruments: int, periods: int = 40) -> pl.DataFrame:
    names = [f"asset-{index}" for index in range(instruments)]
    return pl.DataFrame(
        {
            "time": [time for _ in names for time in range(periods)],
            "instrument": [name for name in names for _ in range(periods)],
            "close": [
                100.0 + time * (index + 1) + 0.37 * math.sin(time + index)
                for index in range(instruments)
                for time in range(periods)
            ],
        }
    )


def _flawed_windows(*, clusters: int = 25) -> EventWindowResult:
    """Windows that are overlapping, censored, retrospective and of unknown adjustment."""

    rows = [(f"event-{index}", f"asset-{index}", index + 5, index + 6) for index in range(clusters)]
    rows.append(("overlap-partner", "asset-0", 6, 7))  # shares prices with event-0
    rows.append(("early", "asset-1", 0, 1))  # left-censored at the series start
    events = pl.DataFrame(
        rows, schema=["event_id", "instrument", "event_time", "available_time"], orient="row"
    )
    return event_windows(
        events,
        _prices(clusters),
        before=1,
        after=2,
        anchor="event_time",
        overlap_policy="keep",
    )


def _clean_windows(*, clusters: int = 25) -> EventWindowResult:
    events = pl.DataFrame(
        {
            "event_id": [f"event-{index}" for index in range(clusters)],
            "instrument": [f"asset-{index}" for index in range(clusters)],
            "event_time": [index + 5 for index in range(clusters)],
            "available_time": [index + 5 for index in range(clusters)],
        }
    )
    return event_windows(
        events,
        _prices(clusters),
        before=1,
        after=2,
        price_adjustment="split_adjusted",
    )


def _canonical(finding: object) -> str:
    return json.dumps(finding.to_dict(), sort_keys=True)  # type: ignore[attr-defined]


def test_event_response_propagates_window_findings_so_the_response_alone_cannot_hide_them() -> None:
    windows = _flawed_windows()
    window_codes = {finding.code for finding in windows.evidence.findings}
    assert set(_WINDOW_CODES) <= window_codes  # fixture really exercises every window finding

    response = event_response(windows, resamples=100, seed=3)

    inherited = [
        finding for finding in windows.evidence.findings if finding.state != FindingState.PASS
    ]
    response_by_code = {finding.code: finding for finding in response.findings}
    for finding in inherited:
        assert _canonical(response_by_code[finding.code]) == _canonical(finding)
    codes = [finding.code for finding in response.findings]
    assert len(codes) == len(set(codes))
    assert codes[0] == "EVENT_CLUSTERED_INFERENCE_AVAILABLE"
    assert codes[1:] == [finding.code for finding in inherited]  # deterministic window order


def test_event_response_support_insufficient_path_also_propagates_window_findings() -> None:
    windows = _flawed_windows(clusters=5)
    response = event_response(windows, resamples=100, seed=3)

    codes = [finding.code for finding in response.findings]
    assert codes[0] == "EVENT_INFERENCE_SUPPORT_INSUFFICIENT"
    assert set(_WINDOW_CODES) <= set(codes)
    assert len(codes) == len(set(codes))


def test_event_response_adds_no_findings_when_windows_are_clean() -> None:
    response = event_response(_clean_windows(), resamples=100, seed=3)

    assert [finding.code for finding in response.findings] == [
        "EVENT_CLUSTERED_INFERENCE_AVAILABLE"
    ]


def test_event_response_pass_finding_states_the_actual_clustering_unit() -> None:
    """The PASS finding must say it clusters on anchor time, not on overlap clusters."""

    windows = _flawed_windows()
    response = event_response(windows, resamples=100, seed=3)
    passing = response.findings[0]

    assert passing.state == FindingState.PASS
    assert passing.evidence["clustering_unit"] == "aligned_anchor_time"
    assert passing.evidence["overlap_cluster_used_for_resampling"] is False
    assert passing.evidence["overlap_clusters_with_multiple_events"] == 1
    assert (
        passing.evidence["events_in_overlap_clusters"]
        == windows.evidence.metrics["overlapping_events"]
    )
    assert response.metadata.method_version == 2
    assert response.metadata.parameters["overlap_cluster_used_for_resampling"] is False
    assert response.metadata.parameters["source_method_version"] == 1


def test_event_windows_offset_zero_response_is_exactly_zero_not_a_residual() -> None:
    """Offset 0 is the anchor row, so its response is the identity p/p - 1 == 0 exactly.

    A -1.1e-16 residual was reported but did not reproduce on the machine that wrote this
    test, so it guards the contract on random float prices and is not a failing-first test.
    """

    generator = np.random.default_rng(20261121)
    instruments, periods = 40, 200
    rows = []
    for instrument in range(instruments):
        path = 100.0 * np.exp(np.cumsum(generator.normal(0.0, 0.02, periods)))
        rows.extend((time, f"asset-{instrument}", float(path[time])) for time in range(periods))
    prices = pl.DataFrame(rows, schema=["time", "instrument", "close"], orient="row")
    events = pl.DataFrame(
        [
            (f"e-{instrument}-{anchor}", f"asset-{instrument}", anchor, anchor)
            for instrument in range(instruments)
            for anchor in range(10, 190, 20)
        ],
        schema=["event_id", "instrument", "event_time", "available_time"],
        orient="row",
    )
    windows = event_windows(events, prices, before=3, after=3, price_adjustment="adjusted")

    anchor_rows = windows.frame.filter(pl.col("offset") == 0)
    assert anchor_rows.height == events.height
    assert (anchor_rows.get_column("response") == 0.0).all()
    assert (anchor_rows.get_column("price") == anchor_rows.get_column("anchor_price")).all()
    others = windows.frame.filter(pl.col("offset") != 0)
    expected = others.get_column("price") / others.get_column("anchor_price") - 1.0
    np.testing.assert_allclose(
        others.get_column("response").to_numpy(), expected.to_numpy(), rtol=1e-12, atol=1e-15
    )

    response = event_response(windows, resamples=100, seed=1, min_clusters=2)
    offset_zero = next(row for row in response.table("event_response") if row["offset"] == 0)
    assert offset_zero["mean_response"] == 0.0
    assert offset_zero["inference_mean"] == 0.0


def test_event_response_records_caller_seed_in_metadata_and_keeps_root_entropy() -> None:
    windows = _clean_windows()
    seeded = event_response(windows, resamples=100, seed=19)
    assert seeded.metadata.seed == 19
    assert seeded.metadata.parameters["root_entropy"] == 19

    unseeded = event_response(windows, resamples=100)
    assert unseeded.metadata.seed is None
    assert isinstance(unseeded.metadata.parameters["root_entropy"], int)

    insufficient = event_response(_clean_windows(clusters=5), resamples=100, seed=23)
    assert insufficient.metadata.seed == 23


def _decay_evidence(periods: int = 24) -> AnalysisResult:
    rows = [
        {
            "observation_time": period,
            "horizon": f"{horizon}D",
            "ic": 0.12 * math.exp(-horizon / 4.0) * (1.0 + 0.02 * math.sin(period)),
        }
        for period in range(periods)
        for horizon in (1, 2, 4, 8)
    ]
    return AnalysisResult(
        metadata=ResultMetadata(method="signal.decay"),
        metrics={"n_horizons": 4},
        tables={"ic_by_period_horizon": tuple(rows)},
    )


@pytest.mark.optional_dependency(reason="SciPy is provided by the statistics extra")
def test_fit_decay_records_caller_seed_in_metadata_and_keeps_root_entropy() -> None:
    pytest.importorskip("scipy")
    seeded = fit_decay(_decay_evidence(), resamples=100, seed=42, minimum_r_squared=0.99)
    assert seeded.metadata.seed == 42
    assert seeded.metadata.parameters["root_entropy"] == 42

    unseeded = fit_decay(_decay_evidence(), resamples=100, minimum_r_squared=0.99)
    assert unseeded.metadata.seed is None
    assert isinstance(unseeded.metadata.parameters["root_entropy"], int)


def test_fit_decay_unidentified_result_also_records_caller_seed() -> None:
    result = fit_decay(_decay_evidence(periods=19), resamples=100, seed=7)

    assert result.findings[0].code == "DECAY_SUPPORT_INSUFFICIENT"
    assert result.metadata.seed == 7
