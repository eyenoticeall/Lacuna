from __future__ import annotations

import numpy as np
import pytest

from lacuna._carriers import ResampleBatch
from lacuna._resampling import indexed_column_means_reference


def test_indexed_column_means_matches_literal_per_resample_reduction() -> None:
    values = np.asarray(
        [[1.0, 10.0], [2.0, 20.0], [4.0, 40.0], [8.0, 80.0]],
        dtype=np.float64,
    )
    samples = (
        np.array([0, 1, 2, 3]),
        np.array([3, 3, 1, 0]),
        np.array([2, 0, 2, 0]),
    )
    batch = ResampleBatch.from_samples(values, samples)

    observed = indexed_column_means_reference(batch)
    expected = np.asarray([values[sample].mean(axis=0) for sample in samples])
    assert observed == pytest.approx(expected)
