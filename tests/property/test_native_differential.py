from __future__ import annotations

import polars as pl
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from lacuna import cv as cv_module
from lacuna.cv import CombinatorialPurgedKFold, PurgedKFold
from lacuna.signal import ic
from lacuna.validation import bootstrap

FINITE = st.floats(
    min_value=-1_000,
    max_value=1_000,
    allow_nan=False,
    allow_infinity=False,
    width=64,
)


@settings(max_examples=30, deadline=None)
@given(
    st.lists(
        st.lists(st.tuples(st.integers(-5, 5), FINITE), min_size=3, max_size=10),
        min_size=1,
        max_size=5,
    )
)
def test_native_grouped_rank_ic_matches_reference_for_random_ties(
    groups: list[list[tuple[int, float]]],
) -> None:
    signal_rows: list[dict[str, object]] = []
    label_rows: list[dict[str, object]] = []
    for period, rows in enumerate(groups):
        for instrument, (signal_value, forward_return) in enumerate(rows):
            signal_rows.append(
                {
                    "time": period,
                    "instrument": instrument,
                    "signal": signal_value,
                }
            )
            label_rows.append(
                {
                    "observation_time": period,
                    "instrument": instrument,
                    "forward_return": forward_return,
                }
            )
    signal = pl.DataFrame(signal_rows)
    labels = pl.DataFrame(label_rows)

    native = ic(signal, labels, method="spearman", use_native=True)
    reference = ic(signal, labels, method="spearman", use_native=False)
    native_rows = native.table("ic_by_period")
    reference_rows = reference.table("ic_by_period")
    assert len(native_rows) == len(reference_rows)  # type: ignore[arg-type]
    for native_row, reference_row in zip(native_rows, reference_rows, strict=True):  # type: ignore[arg-type]
        assert native_row["observation_time"] == reference_row["observation_time"]
        assert native_row["n_observations"] == reference_row["n_observations"]
        if reference_row["ic"] is None:
            assert native_row["ic"] is None
        else:
            assert native_row["ic"] == pytest.approx(reference_row["ic"], abs=1e-14)


@settings(max_examples=20, deadline=None)
@given(st.lists(FINITE, min_size=2, max_size=30), st.integers(min_value=0, max_value=2**32))
def test_native_bootstrap_reduction_matches_numpy_reference(values: list[float], seed: int) -> None:
    native = bootstrap(
        values,
        method="circular",
        block_length=min(4, len(values)),
        resamples=100,
        seed=seed,
        store_distribution=True,
        use_native=True,
    )
    reference = bootstrap(
        values,
        method="circular",
        block_length=min(4, len(values)),
        resamples=100,
        seed=seed,
        store_distribution=True,
        use_native=False,
    )
    native_values = [row["statistic"] for row in native.table("resample_distribution")]  # type: ignore[union-attr]
    reference_values = [
        row["statistic"]
        for row in reference.table("resample_distribution")  # type: ignore[union-attr]
    ]
    assert native_values == pytest.approx(reference_values, rel=1e-14, abs=1e-12)


@settings(max_examples=30, deadline=None)
@given(
    st.lists(st.integers(min_value=1, max_value=8), min_size=6, max_size=30),
    st.integers(min_value=2, max_value=5),
    st.integers(min_value=0, max_value=3),
)
def test_native_and_reference_interval_purge_match_random_panels(
    lengths: list[int], n_splits: int, embargo: int
) -> None:
    starts = list(range(len(lengths)))
    frame = pl.DataFrame(
        {
            "observation_time": starts,
            "label_start": starts,
            "label_end": [start + length for start, length in zip(starts, lengths, strict=True)],
        }
    )
    splits = min(n_splits, len(lengths))
    native = PurgedKFold(n_splits=splits, embargo=embargo, use_native=True).split(frame)
    reference = PurgedKFold(n_splits=splits, embargo=embargo, use_native=False).split(frame)
    assert native.folds == reference.folds


@settings(max_examples=30, deadline=None)
@given(
    st.lists(st.integers(min_value=1, max_value=8), min_size=6, max_size=24),
    st.integers(min_value=3, max_value=6),
    st.integers(min_value=1, max_value=2),
    st.integers(min_value=0, max_value=3),
)
def test_complete_native_cpcv_matches_reference_for_random_unsorted_panels(
    lengths: list[int], requested_groups: int, requested_test_groups: int, embargo: int
) -> None:
    periods = list(range(len(lengths)))
    source_order = periods[::2] + periods[1::2]
    frame = pl.DataFrame(
        {
            "observation_time": source_order,
            "label_start": source_order,
            "label_end": [period + lengths[period] for period in source_order],
        }
    )
    n_groups = min(requested_groups, len(periods))
    n_test_groups = min(requested_test_groups, n_groups - 1)
    splitter = {
        "n_groups": n_groups,
        "n_test_groups": n_test_groups,
        "embargo": embargo,
    }
    reference = CombinatorialPurgedKFold(**splitter, use_native=False).split(frame)
    prior_threshold = cv_module._CPCV_NATIVE_ROLE_EVALUATION_THRESHOLD
    cv_module._CPCV_NATIVE_ROLE_EVALUATION_THRESHOLD = 0
    try:
        native = CombinatorialPurgedKFold(**splitter, use_native=True).split(frame)
    finally:
        cv_module._CPCV_NATIVE_ROLE_EVALUATION_THRESHOLD = prior_threshold

    assert native.folds == reference.folds
    assert native.paths == reference.paths
    assert native.evidence.metrics == reference.evidence.metrics
    for name in ("groups", "combinations", "folds", "paths"):
        assert native.evidence.table(name) == reference.evidence.table(name)
