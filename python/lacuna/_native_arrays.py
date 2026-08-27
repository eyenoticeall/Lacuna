"""Checked private NumPy carriers for bulk native calls."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeVar

import numpy as np
import numpy.typing as npt
import polars as pl

_Scalar = TypeVar("_Scalar", bound=np.generic)


@dataclass(frozen=True, slots=True)
class NativeArray:
    """A read-only native-endian one-dimensional array and copy accounting."""

    values: npt.NDArray[np.generic]
    copied_bytes: int


def _readonly_array(
    values: object,
    *,
    dtype: np.dtype[_Scalar],
    name: str,
) -> NativeArray:
    array = np.asarray(values)
    if array.ndim != 1:
        raise ValueError(f"{name} must be one-dimensional")

    compatible = (
        array.dtype == dtype
        and array.dtype.isnative
        and array.flags.c_contiguous
        and array.flags.aligned
    )
    if compatible:
        normalized = array.view()
        copied_bytes = 0
    else:
        normalized = np.require(array, dtype=dtype, requirements=("C", "A", "O"))
        copied_bytes = int(normalized.nbytes)
    normalized.setflags(write=False)
    return NativeArray(values=normalized, copied_bytes=copied_bytes)


def readonly_float64(values: object, *, name: str) -> NativeArray:
    """Normalize numeric input to the native float64 boundary contract."""

    if isinstance(values, pl.Series):
        try:
            array = values.to_numpy(writable=False, allow_copy=False)
            return _readonly_array(array, dtype=np.dtype(np.float64), name=name)
        except RuntimeError:
            array = values.cast(pl.Float64).rechunk().to_numpy(writable=False)
            normalized = _readonly_array(array, dtype=np.dtype(np.float64), name=name)
            return NativeArray(values=normalized.values, copied_bytes=int(array.nbytes))
    return _readonly_array(values, dtype=np.dtype(np.float64), name=name)


def readonly_int64(values: object, *, name: str) -> NativeArray:
    """Normalize integer input to the native int64 boundary contract."""

    return _readonly_array(values, dtype=np.dtype(np.int64), name=name)
