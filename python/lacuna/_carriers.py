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


def _checked_int64_vector(value: object, *, name: str) -> Int64Vector:
    vector = cast(Int64Vector, np.asarray(value))
    if vector.dtype != np.dtype(np.int64) or vector.ndim != 1:
        raise DataContractError(f"{name} must be a one-dimensional int64 array")
    if not vector.flags.c_contiguous:
        raise DataContractError(f"{name} must be C-contiguous")
    vector.setflags(write=False)
    return vector


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


@dataclass(frozen=True, slots=True)
class CompactFoldBuffer:
    """CSR role indices and CPCV path incidence behind the public fold types."""

    row_count: int
    group_count: int
    train_indices: Int64Vector
    train_offsets: Int64Vector
    test_indices: Int64Vector
    test_offsets: Int64Vector
    purged_indices: Int64Vector
    purged_offsets: Int64Vector
    embargoed_indices: Int64Vector
    embargoed_offsets: Int64Vector
    path_fold_by_group: Int64Vector
    path_offsets: Int64Vector

    def __post_init__(self) -> None:
        if self.row_count < 1 or self.group_count < 2:
            raise DataContractError("compact fold dimensions must contain rows and two groups")
        names = (
            "train_indices",
            "train_offsets",
            "test_indices",
            "test_offsets",
            "purged_indices",
            "purged_offsets",
            "embargoed_indices",
            "embargoed_offsets",
            "path_fold_by_group",
            "path_offsets",
        )
        vectors = {name: _checked_int64_vector(getattr(self, name), name=name) for name in names}
        role_names = ("train", "test", "purged", "embargoed")
        offset_sizes: set[int] = set()
        for role in role_names:
            indices = vectors[f"{role}_indices"]
            offsets = vectors[f"{role}_offsets"]
            if offsets.size < 2 or offsets[0] != 0 or offsets[-1] != indices.size:
                raise DataContractError(f"{role} offsets must span the complete index buffer")
            if bool((np.diff(offsets) < 0).any()):
                raise DataContractError(f"{role} offsets must be non-decreasing")
            if bool((indices < 0).any()) or bool((indices >= self.row_count).any()):
                raise DataContractError(f"{role} indices must point inside the source frame")
            offset_sizes.add(int(offsets.size))
        if len(offset_sizes) != 1:
            raise DataContractError("all CPCV role buffers must describe the same fold count")

        fold_count = next(iter(offset_sizes)) - 1
        assignment_counts: npt.NDArray[np.uint8] = np.empty(self.row_count, dtype=np.uint8)
        for fold in range(fold_count):
            role_slices = [
                self._slice(vectors[f"{role}_indices"], vectors[f"{role}_offsets"], fold)
                for role in role_names
            ]
            for role, role_slice in zip(role_names, role_slices, strict=True):
                if bool((np.diff(role_slice) <= 0).any()):
                    raise DataContractError(f"{role} indices must be unique and source ordered")
            if sum(role_slice.size for role_slice in role_slices) != self.row_count:
                raise DataContractError("every source row must have exactly one role in every fold")
            assignment_counts.fill(0)
            for role_slice in role_slices:
                assignment_counts[role_slice] += 1
            if not bool(np.all(assignment_counts == 1)):
                raise DataContractError("every source row must have exactly one role in every fold")

        paths = vectors["path_fold_by_group"]
        path_offsets = vectors["path_offsets"]
        if path_offsets.size < 2 or path_offsets[0] != 0 or path_offsets[-1] != paths.size:
            raise DataContractError("path offsets must span the complete incidence buffer")
        if bool((np.diff(path_offsets) != self.group_count).any()):
            raise DataContractError("every CPCV path must contain exactly one fold per group")
        if bool((paths < 0).any()) or bool((paths >= fold_count).any()):
            raise DataContractError("path incidence must point to an existing fold")
        for name, vector in vectors.items():
            object.__setattr__(self, name, vector)

    @staticmethod
    def _slice(indices: Int64Vector, offsets: Int64Vector, position: int) -> Int64Vector:
        start = int(offsets[position])
        end = int(offsets[position + 1])
        return indices[start:end]

    @property
    def fold_count(self) -> int:
        return int(self.train_offsets.size - 1)

    @property
    def path_count(self) -> int:
        return int(self.path_offsets.size - 1)

    def role(self, fold: int, name: str) -> tuple[int, ...]:
        """Project one checked role slice into the stable public tuple representation."""

        if not 0 <= fold < self.fold_count:
            raise IndexError("fold index is out of range")
        if name not in {"train", "test", "purged", "embargoed"}:
            raise ValueError("unknown fold role")
        indices = cast(Int64Vector, getattr(self, f"{name}_indices"))
        offsets = cast(Int64Vector, getattr(self, f"{name}_offsets"))
        return cast(tuple[int, ...], tuple(self._slice(indices, offsets, fold).tolist()))

    def path(self, position: int) -> tuple[int, ...]:
        """Project one checked path-incidence slice into the public tuple representation."""

        if not 0 <= position < self.path_count:
            raise IndexError("path index is out of range")
        return cast(
            tuple[int, ...],
            tuple(self._slice(self.path_fold_by_group, self.path_offsets, position).tolist()),
        )


__all__: list[str] = []
