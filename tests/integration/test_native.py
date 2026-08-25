from __future__ import annotations

import math

import numpy as np
import pytest

from lacuna import _native
from lacuna.native import native_status
from lacuna.signal import ic


def test_native_extension_is_available() -> None:
    status = native_status()
    assert status.available is True
    assert status.version == _native.version()


def test_checked_mean_crosses_the_native_boundary() -> None:
    assert _native.checked_mean([1.0, 2.0, 6.0]) == 3.0


def test_checked_mean_rejects_non_finite_values() -> None:
    with pytest.raises(ValueError, match="index 1"):
        _native.checked_mean([1.0, math.nan])


def test_native_grouped_rank_ic_uses_average_ties() -> None:
    result = _native.grouped_rank_ic(
        [1.0, 2.0, 2.0, 4.0, 4.0, 3.0],
        [1.0, 2.0, 3.0, 4.0, 1.0, 2.0],
        [0, 4, 6],
    )
    assert result[0] == pytest.approx(0.9486832980505138)
    assert result[1] == -1.0


def test_native_bootstrap_mean_reduction() -> None:
    assert _native.bootstrap_means(
        [1.0, 2.0, 5.0],
        [0, 0, 2, 1, 2, 2],
        [0, 3, 6],
    ) == pytest.approx([7 / 3, 4.0])


def test_native_interval_purge_uses_half_open_intervals() -> None:
    assert _native.interval_purge(
        [0, 2, 3, 5],
        [2, 3, 5, 7],
        [2],
        [4],
    ) == [False, True, True, False]


def test_native_grouped_rank_ic_matches_reference_path() -> None:
    signal = np.array([3.0, 1.0, 2.0, 2.0, 8.0, 7.0, 6.0, 5.0])
    labels = np.array([4.0, 1.0, 3.0, 2.0, 1.0, 2.0, 3.0, 4.0])
    native = ic(signal, labels, method="spearman", use_native=True)
    reference = ic(signal, labels, method="spearman", use_native=False)
    assert native.metrics["mean_ic"] == pytest.approx(reference.metrics["mean_ic"], abs=1e-15)
    assert native.metadata.parameters["backend"] == "rust_native"
