from __future__ import annotations

import polars as pl
from hypothesis import given
from hypothesis import strategies as st

from lacuna.cv import CombinatorialPurgedKFold, PurgedKFold


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


@given(
    st.integers(min_value=3, max_value=7),
    st.integers(min_value=1, max_value=3),
)
def test_every_cpcv_path_covers_every_observation_once(
    n_groups: int,
    requested_test_groups: int,
) -> None:
    n_test_groups = min(requested_test_groups, n_groups - 1)
    periods = list(range(n_groups * 2))
    frame = pl.DataFrame(
        {
            "observation_time": periods,
            "label_start": periods,
            "label_end": [period + 1 for period in periods],
        }
    )
    result = CombinatorialPurgedKFold(
        n_groups=n_groups,
        n_test_groups=n_test_groups,
        use_native=False,
    ).split(frame)

    for path in result.paths:
        assert sorted(path.test_indices) == periods
        assert len(set(path.test_indices)) == len(periods)
        for group, fold_number in enumerate(path.fold_by_group):
            test_groups = result.evidence.table("combinations")[fold_number]["test_groups"]
            assert group in test_groups
