from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from lacuna._native_arrays import (
    readonly_float64,
    readonly_float64_matrix,
    readonly_int64,
    readonly_int64_matrix,
)


def test_readonly_float64_preserves_compatible_input_without_mutating_flags() -> None:
    source = np.asarray([1.0, 2.0, 3.0], dtype=np.float64)
    normalized = readonly_float64(source, name="values")

    assert normalized.copied_bytes == 0
    assert normalized.values.flags.writeable is False
    assert source.flags.writeable is True
    assert np.shares_memory(source, normalized.values)


def test_readonly_int64_copies_strided_and_wrong_endian_inputs() -> None:
    source = np.arange(8, dtype=np.int64)[::2]
    normalized = readonly_int64(source, name="indices")
    assert normalized.copied_bytes == normalized.values.nbytes
    assert normalized.values.flags.c_contiguous
    assert normalized.values.flags.aligned
    assert normalized.values.flags.writeable is False

    wrong_endian = np.asarray([1, 2], dtype=">i8")
    endian_normalized = readonly_int64(wrong_endian, name="indices")
    assert endian_normalized.values.dtype.isnative
    assert endian_normalized.copied_bytes == endian_normalized.values.nbytes


def test_readonly_float64_records_polars_copy_fallback() -> None:
    series = pl.concat(
        [pl.Series("value", [1.0]), pl.Series("value", [2.0])],
        rechunk=False,
    )
    normalized = readonly_float64(series, name="value")
    assert normalized.values.tolist() == [1.0, 2.0]
    assert normalized.values.flags.writeable is False
    assert normalized.copied_bytes == normalized.values.nbytes


def test_native_array_normalization_rejects_multidimensional_input() -> None:
    with pytest.raises(ValueError, match="one-dimensional"):
        readonly_float64(np.ones((2, 2)), name="values")


def test_native_matrix_normalization_preserves_or_accounts_for_storage() -> None:
    source = np.arange(12, dtype=np.float64).reshape(3, 4)
    normalized = readonly_float64_matrix(source, name="matrix")
    assert normalized.values.shape == (3, 4)
    assert normalized.copied_bytes == 0
    assert normalized.values.flags.writeable is False
    assert np.shares_memory(source, normalized.values)

    transposed = np.arange(12, dtype=np.int64).reshape(3, 4).T
    copied = readonly_int64_matrix(transposed, name="groups")
    assert copied.values.shape == (4, 3)
    assert copied.copied_bytes == copied.values.nbytes
    assert copied.values.flags.c_contiguous
    assert copied.values.flags.writeable is False


def test_native_matrix_normalization_rejects_vectors() -> None:
    with pytest.raises(ValueError, match="two-dimensional"):
        readonly_float64_matrix(np.ones(4), name="matrix")
