"""Internal deterministic resampling primitives shared by inferential methods."""

from __future__ import annotations

from typing import TypeAlias

import numpy as np
import numpy.typing as npt

IntMatrix: TypeAlias = npt.NDArray[np.int64]


def stationary_bootstrap_indices(
    sample_count: int,
    *,
    resamples: int,
    expected_block_length: float,
    rng: np.random.Generator,
) -> IntMatrix:
    """Draw stationary-bootstrap indices with circular continuation."""

    if sample_count < 1:
        raise ValueError("stationary bootstrap requires at least one sample")
    if resamples < 1:
        raise ValueError("resamples must be positive")
    if not np.isfinite(expected_block_length) or expected_block_length < 1.0:
        raise ValueError("expected_block_length must be finite and at least one")
    restart_probability = 1.0 / expected_block_length
    indices: IntMatrix = np.empty((resamples, sample_count), dtype=np.int64)
    indices[:, 0] = rng.integers(0, sample_count, size=resamples)
    for position in range(1, sample_count):
        restart = rng.random(resamples) < restart_probability
        continued: npt.NDArray[np.int64] = (indices[:, position - 1] + 1) % sample_count
        replacements = rng.integers(0, sample_count, size=resamples)
        indices[:, position] = np.where(restart, replacements, continued)
    return indices


__all__ = ["stationary_bootstrap_indices"]
