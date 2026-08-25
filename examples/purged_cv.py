"""Inspect half-open interval purging and observation-count embargo."""

from __future__ import annotations

import polars as pl

import lacuna as lc

labels = pl.DataFrame(
    {
        "observation_time": list(range(8)),
        "label_start": list(range(8)),
        "label_end": [value + 2 for value in range(8)],
    }
)
split = lc.cv.PurgedKFold(n_splits=4, embargo=1).split(labels)

for fold in split.folds:
    print(
        fold.fold,
        {
            "train": fold.train_indices,
            "test": fold.test_indices,
            "purged": fold.purged_indices,
            "embargoed": fold.embargoed_indices,
        },
    )
