from __future__ import annotations

import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest

import lacuna
from lacuna import _native
from lacuna.native import native_status
from lacuna.signal import ic


def test_native_extension_is_available() -> None:
    status = native_status()
    assert status.available is True
    assert status.version == _native.version()
    assert lacuna.__version__ == _native.version()


def test_checked_mean_crosses_the_native_boundary() -> None:
    assert _native.checked_mean([1.0, 2.0, 6.0]) == 3.0


def test_checked_mean_rejects_non_finite_values() -> None:
    with pytest.raises(ValueError, match="index 1"):
        _native.checked_mean([1.0, math.nan])


def test_native_grouped_rank_ic_uses_average_ties() -> None:
    values, validity = _native.grouped_rank_ic(
        np.asarray([1.0, 2.0, 2.0, 4.0, 4.0, 3.0], dtype=np.float64),
        np.asarray([1.0, 2.0, 3.0, 4.0, 1.0, 2.0], dtype=np.float64),
        np.asarray([0, 4, 6], dtype=np.int64),
    )
    assert values.dtype == np.float64
    assert validity.dtype == np.uint8
    assert validity.tolist() == [1, 1]
    assert values[0] == pytest.approx(0.9486832980505138)
    assert values[1] == -1.0


def test_native_grouped_rank_ic_treats_signed_zero_as_a_tie() -> None:
    values, validity = _native.grouped_rank_ic(
        np.asarray([1.0, 2.0, 3.0, 1.0, 2.0], dtype=np.float64),
        np.asarray([0.0, -0.0, 1.0, 0.0, -0.0], dtype=np.float64),
        np.asarray([0, 3, 5], dtype=np.int64),
    )
    assert values[0] == pytest.approx(0.8660254037844387)
    assert validity.tolist() == [1, 0]
    assert values[1] == 0.0


def test_native_bootstrap_mean_reduction() -> None:
    result = _native.bootstrap_means(
        np.asarray([1.0, 2.0, 5.0], dtype=np.float64),
        np.asarray([0, 0, 2, 1, 2, 2], dtype=np.int64),
        np.asarray([0, 3, 6], dtype=np.int64),
    )
    assert result.dtype == np.float64
    assert result == pytest.approx([7 / 3, 4.0])


def test_native_interval_purge_uses_half_open_intervals() -> None:
    result = _native.interval_purge(
        np.asarray([0, 2, 3, 5], dtype=np.int64),
        np.asarray([2, 3, 5, 7], dtype=np.int64),
        np.asarray([2], dtype=np.int64),
        np.asarray([4], dtype=np.int64),
    )
    assert result.dtype == np.uint8
    assert result.tolist() == [0, 1, 1, 0]


def test_native_array_boundary_rejects_wrong_dtype_and_strided_input() -> None:
    with pytest.raises(TypeError):
        _native.bootstrap_means(
            np.asarray([1.0, 2.0], dtype=np.float32),
            np.asarray([0, 1], dtype=np.int64),
            np.asarray([0, 2], dtype=np.int64),
        )

    strided = np.arange(8, dtype=np.float64)[::2]
    with pytest.raises(ValueError, match="C-contiguous"):
        _native.bootstrap_means(
            strided,
            np.asarray([0, 1], dtype=np.int64),
            np.asarray([0, 2], dtype=np.int64),
        )

    storage = np.zeros(25, dtype=np.uint8)
    misaligned = storage[1:].view(np.float64)
    assert misaligned.flags.aligned is False
    with pytest.raises(ValueError, match="aligned"):
        _native.bootstrap_means(
            misaligned,
            np.asarray([0, 1], dtype=np.int64),
            np.asarray([0, 2], dtype=np.int64),
        )


def test_native_array_boundary_rejects_negative_indices_and_bad_offsets() -> None:
    values = np.asarray([1.0, 2.0], dtype=np.float64)
    with pytest.raises(ValueError, match=r"indices\[1\].*non-negative"):
        _native.bootstrap_means(
            values,
            np.asarray([0, -1], dtype=np.int64),
            np.asarray([0, 2], dtype=np.int64),
        )
    with pytest.raises(ValueError, match="offsets"):
        _native.bootstrap_means(
            values,
            np.asarray([0, 1], dtype=np.int64),
            np.asarray([1, 2], dtype=np.int64),
        )


def test_native_boundary_snapshots_mutable_alias_before_detaching() -> None:
    size = 1_000_000
    signal = np.arange(size, dtype=np.float64)
    labels = signal.copy()
    offsets = np.asarray([0, size], dtype=np.int64)
    mutation_ready = threading.Event()
    mutation_finished = threading.Event()

    def mutate_alias() -> None:
        mutation_ready.wait()
        time.sleep(0.01)
        signal[:] = signal[::-1]
        mutation_finished.set()

    worker = threading.Thread(target=mutate_alias)
    worker.start()
    mutation_ready.set()
    values, validity = _native.grouped_rank_ic(signal, labels, offsets)
    worker.join()

    assert mutation_finished.is_set()
    assert validity.tolist() == [1]
    assert values.tolist() == pytest.approx([1.0], abs=1e-15)


def test_native_boundary_supports_concurrent_independent_calls() -> None:
    def reduce(offset: int) -> list[float]:
        values = np.arange(offset, offset + 100, dtype=np.float64)
        indices = np.arange(100, dtype=np.int64)
        offsets = np.asarray([0, 50, 100], dtype=np.int64)
        return _native.bootstrap_means(values, indices, offsets).tolist()

    with ThreadPoolExecutor(max_workers=4) as executor:
        outputs = list(executor.map(reduce, range(8)))

    assert outputs == [[offset + 24.5, offset + 74.5] for offset in range(8)]


def test_native_grouped_rank_ic_matches_reference_path() -> None:
    signal = np.array([3.0, 1.0, 2.0, 2.0, 8.0, 7.0, 6.0, 5.0])
    labels = np.array([4.0, 1.0, 3.0, 2.0, 1.0, 2.0, 3.0, 4.0])
    native = ic(signal, labels, method="spearman", use_native=True)
    reference = ic(signal, labels, method="spearman", use_native=False)
    assert native.metrics["mean_ic"] == pytest.approx(reference.metrics["mean_ic"], abs=1e-15)
    assert native.metadata.parameters["backend"] == "rust_native"
