from __future__ import annotations

import polars as pl
from hypothesis import given
from hypothesis import strategies as st

from lacuna.cv import PurgedKFold


@given(
    st.lists(st.integers(min_value=1, max_value=5), min_size=6, max_size=30),
    st.integers(min_value=2, max_value=5),
)
def test_purging_never_retains_an_overlapping_interval(lengths: list[int], n_splits: int) -> None:
    periods = list(range(len(lengths)))
    frame = pl.DataFrame(
        {
            "observation_time": periods,
            "label_start": periods,
            "label_end": [start + length for start, length in zip(periods, lengths, strict=True)],
        }
    )
    splitter = PurgedKFold(n_splits=min(n_splits, len(periods)), use_native=False)
    result = splitter.split(frame)
    for fold in result.folds:
        for train_index in fold.train_indices:
            train_start = periods[train_index]
            train_end = periods[train_index] + lengths[train_index]
            for test_index in fold.test_indices:
                test_start = periods[test_index]
                test_end = periods[test_index] + lengths[test_index]
                assert not (train_start < test_end and train_end > test_start)
