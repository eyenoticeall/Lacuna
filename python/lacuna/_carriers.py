"""Private compact carriers used behind stable public result contracts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TypeAlias, cast

import numpy as np
import numpy.typing as npt

from lacuna.exceptions import DataContractError, MethodContractError

FloatMatrix: TypeAlias = npt.NDArray[np.float64]
UInt8Matrix: TypeAlias = npt.NDArray[np.uint8]
Int64Vector: TypeAlias = npt.NDArray[np.int64]


@dataclass(frozen=True, slots=True)
class CostComponentBatch:
    """Contiguous cost-component values plus explicit validity and Python-owned names."""

    names: tuple[str, ...]
    values: FloatMatrix
    validity: UInt8Matrix

    def __post_init__(self) -> None:
        names = tuple(self.names)
        if len(names) != len(set(names)) or any(not name for name in names):
            raise MethodContractError("cost component names must be unique and non-empty")
        values = cast(FloatMatrix, np.asarray(self.values))
        validity = cast(UInt8Matrix, np.asarray(self.validity))
        if values.dtype != np.dtype(np.float64) or values.ndim != 2:
            raise DataContractError("cost component values must be a two-dimensional float64 array")
        if validity.dtype != np.dtype(np.uint8) or validity.ndim != 2:
            raise DataContractError("cost component validity must be a two-dimensional uint8 array")
        if values.shape != validity.shape or values.shape[0] != len(names):
            raise DataContractError("cost component names, values, and validity must align")
        if not values.flags.c_contiguous or not validity.flags.c_contiguous:
            raise DataContractError("cost component buffers must be C-contiguous")
        if bool(((validity != 0) & (validity != 1)).any()):
            raise DataContractError("cost component validity codes must be 0 or 1")
        valid_values = values[validity.astype(bool, copy=False)]
        if bool((~np.isfinite(valid_values)).any()) or bool((valid_values < 0.0).any()):
            raise DataContractError("valid cost component values must be finite and non-negative")
        invalid_values = values[validity == 0]
        if bool((invalid_values != 0.0).any()):
            raise DataContractError("invalid cost component cells must use a zero value sentinel")
        values.setflags(write=False)
        validity.setflags(write=False)
        object.__setattr__(self, "names", names)
        object.__setattr__(self, "values", values)
        object.__setattr__(self, "validity", validity)

    @classmethod
    def from_components(
        cls,
        components: Mapping[str, Sequence[float | None]],
        *,
        row_count: int,
    ) -> CostComponentBatch:
        """Snapshot tuple-backed public components into one internal contiguous batch."""

        if row_count < 0:
            raise MethodContractError("row_count must be non-negative")
        names = tuple(components)
        values: FloatMatrix = np.zeros((len(names), row_count), dtype=np.float64)
        validity: UInt8Matrix = np.ones((len(names), row_count), dtype=np.uint8)
        for component_index, name in enumerate(names):
            component = components[name]
            if len(component) != row_count:
                raise DataContractError("cost component rows do not align with the trade frame")
            for row_index, value in enumerate(component):
                if value is None:
                    validity[component_index, row_index] = 0
                else:
                    values[component_index, row_index] = float(value)
        return cls(names=names, values=values, validity=validity)

    @property
    def row_count(self) -> int:
        return int(self.values.shape[1])

    @property
    def row_validity(self) -> npt.NDArray[np.bool_]:
        if not self.names:
            return np.ones(self.row_count, dtype=np.bool_)
        return np.all(self.validity == 1, axis=0)

    @property
    def row_totals(self) -> npt.NDArray[np.float64]:
        return np.sum(self.values, axis=0, dtype=np.float64)

    def component_totals(self) -> dict[str, float | None]:
        totals: dict[str, float | None] = {}
        for index, name in enumerate(self.names):
            totals[name] = (
                float(np.sum(self.values[index], dtype=np.float64))
                if bool(np.all(self.validity[index] == 1))
                else None
            )
        return totals


@dataclass(frozen=True, slots=True)
class ResampleBatch:
    """A value matrix and flattened, offset-delimited resample indices."""

    values: FloatMatrix
    indices: Int64Vector
    offsets: Int64Vector

    def __post_init__(self) -> None:
        values = cast(FloatMatrix, np.asarray(self.values))
        indices = cast(Int64Vector, np.asarray(self.indices))
        offsets = cast(Int64Vector, np.asarray(self.offsets))
        if values.dtype != np.dtype(np.float64) or values.ndim != 2:
            raise DataContractError("resample values must be a two-dimensional float64 array")
        if indices.dtype != np.dtype(np.int64) or indices.ndim != 1:
            raise DataContractError("resample indices must be a one-dimensional int64 array")
        if offsets.dtype != np.dtype(np.int64) or offsets.ndim != 1:
            raise DataContractError("resample offsets must be a one-dimensional int64 array")
        if not values.flags.c_contiguous or not indices.flags.c_contiguous:
            raise DataContractError("resample values and indices must be C-contiguous")
        if not offsets.flags.c_contiguous:
            raise DataContractError("resample offsets must be C-contiguous")
        if values.shape[0] < 1 or values.shape[1] < 1:
            raise DataContractError("resample values must contain at least one row and column")
        if bool((~np.isfinite(values)).any()):
            raise DataContractError("resample values must be finite")
        if offsets.size < 2 or offsets[0] != 0 or offsets[-1] != indices.size:
            raise DataContractError("resample offsets must span the complete index buffer")
        if bool((np.diff(offsets) <= 0).any()):
            raise DataContractError("resample offsets must define non-empty increasing samples")
        if bool((indices < 0).any()) or bool((indices >= values.shape[0]).any()):
            raise DataContractError("resample indices must point inside the value matrix")
        values.setflags(write=False)
        indices.setflags(write=False)
        offsets.setflags(write=False)
        object.__setattr__(self, "values", values)
        object.__setattr__(self, "indices", indices)
        object.__setattr__(self, "offsets", offsets)

    @classmethod
    def from_samples(
        cls,
        values: FloatMatrix,
        samples: Sequence[npt.NDArray[np.intp]],
    ) -> ResampleBatch:
        """Build a contiguous carrier without Python objects in the stored representation."""

        if not samples:
            raise DataContractError("resample batches must contain at least one sample")
        lengths = np.asarray([sample.size for sample in samples], dtype=np.int64)
        offsets = np.empty(lengths.size + 1, dtype=np.int64)
        offsets[0] = 0
        np.cumsum(lengths, out=offsets[1:])
        indices = np.concatenate(samples).astype(np.int64, copy=False)
        matrix = np.ascontiguousarray(values, dtype=np.float64)
        return cls(values=matrix, indices=indices, offsets=offsets)

    @property
    def resamples(self) -> int:
        return int(self.offsets.size - 1)


__all__: list[str] = []
