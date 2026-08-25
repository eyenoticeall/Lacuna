"""scikit-learn-compatible wrappers for Lacuna temporal splitters."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import TypeAlias

import numpy as np
import numpy.typing as npt

from lacuna.cv import (
    CombinatorialPurgedKFold,
    CombinatorialSplitResult,
    PurgedKFold,
    SplitResult,
    WalkForward,
)
from lacuna.exceptions import DataContractError, MethodContractError
from lacuna.types import AnalysisResult

SupportedSplitter = WalkForward | PurgedKFold | CombinatorialPurgedKFold
IndexArray: TypeAlias = npt.NDArray[np.int64]


def _sample_count(value: object, *, name: str) -> int:
    try:
        count = len(value)  # type: ignore[arg-type]
    except TypeError as error:
        raise DataContractError(f"{name} must expose a sample count through len()") from error
    if count < 0:  # pragma: no cover - Python length invariant
        raise DataContractError(f"{name} reported an invalid sample count")
    return count


class SklearnCV:
    """Immutable sklearn-style view over one precomputed Lacuna split result.

    Precomputing freezes the row ordering and prevents a mutable interval table
    from changing folds between estimator evaluations. The class deliberately
    avoids importing scikit-learn; its ``split`` and ``get_n_splits`` methods
    satisfy the public cross-validator protocol.
    """

    def __init__(
        self,
        splitter: SupportedSplitter,
        data: object,
        *,
        time: str | None = None,
        label_start: str = "label_start",
        label_end: str = "label_end",
    ) -> None:
        if not isinstance(splitter, WalkForward | PurgedKFold | CombinatorialPurgedKFold):
            raise MethodContractError(
                "splitter must be WalkForward, PurgedKFold, or CombinatorialPurgedKFold"
            )
        if time is not None and (not isinstance(time, str) or not time):
            raise MethodContractError("time must be a non-empty column name")
        if any(not isinstance(value, str) or not value for value in (label_start, label_end)):
            raise MethodContractError("label interval columns must be non-empty names")

        result: SplitResult | CombinatorialSplitResult
        if isinstance(splitter, WalkForward):
            resolved_time = time or "time"
            result = splitter.split(data, time=resolved_time)
        else:
            resolved_time = time or "observation_time"
            result = splitter.split(
                data,
                time=resolved_time,
                label_start=label_start,
                label_end=label_end,
            )

        self._folds = tuple(
            (tuple(fold.train_indices), tuple(fold.test_indices)) for fold in result.folds
        )
        input_evidence = result.evidence.metadata.parameters.get("input")
        if not isinstance(input_evidence, Mapping):  # pragma: no cover - splitter invariant
            raise RuntimeError("Lacuna splitter evidence is missing input diagnostics")
        rows = input_evidence.get("rows")
        if not isinstance(rows, int):  # pragma: no cover - splitter invariant
            raise RuntimeError("Lacuna splitter evidence is missing its input row count")
        self._n_samples = rows
        self._evidence = result.evidence

    @property
    def evidence(self) -> AnalysisResult:
        """Return the original Lacuna fold evidence."""

        return self._evidence

    def _validate_inputs(self, X: object | None, y: object | None, groups: object | None) -> None:
        if groups is not None:
            raise MethodContractError(
                "groups are not consumed by Lacuna temporal splitters; encode grouping in the "
                "precomputed interval table"
            )
        if X is not None and _sample_count(X, name="X") != self._n_samples:
            raise DataContractError("X row count does not match the precomputed interval table")
        if y is not None and _sample_count(y, name="y") != self._n_samples:
            raise DataContractError("y row count does not match the precomputed interval table")

    def split(
        self,
        X: object,
        y: object | None = None,
        groups: object | None = None,
    ) -> Iterator[tuple[IndexArray, IndexArray]]:
        """Yield independent integer index arrays in sklearn's expected form."""

        self._validate_inputs(X, y, groups)
        for train, test in self._folds:
            yield np.asarray(train, dtype=np.int64), np.asarray(test, dtype=np.int64)

    def get_n_splits(
        self,
        X: object | None = None,
        y: object | None = None,
        groups: object | None = None,
    ) -> int:
        """Return the frozen fold count after optional shape validation."""

        self._validate_inputs(X, y, groups)
        return len(self._folds)

    def __repr__(self) -> str:
        return f"SklearnCV(n_splits={len(self._folds)}, n_samples={self._n_samples})"


def as_sklearn_cv(
    splitter: SupportedSplitter,
    data: object,
    *,
    time: str | None = None,
    label_start: str = "label_start",
    label_end: str = "label_end",
) -> SklearnCV:
    """Freeze a Lacuna temporal splitter behind sklearn's CV protocol."""

    return SklearnCV(
        splitter,
        data,
        time=time,
        label_start=label_start,
        label_end=label_end,
    )


__all__ = ["SklearnCV", "SupportedSplitter", "as_sklearn_cv"]
