"""Dataframe interoperability helpers."""

from typing import TYPE_CHECKING

from lacuna.adapters.backtest import (
    BacktestArtifactKind,
    BacktestSchema,
    BacktestSemantics,
    adapt_backtest,
)
from lacuna.adapters.duckdb import from_duckdb
from lacuna.adapters.polars import (
    FrameSummary,
    PolarsFrame,
    frame_summary,
    require_columns,
    to_polars,
)
from lacuna.adapters.types import AdaptedFrame
from lacuna.adapters.vendor import (
    AvailabilityPolicy,
    RevisionPolicy,
    VendorSchema,
    adapt_vendor,
)

if TYPE_CHECKING:
    from lacuna.adapters.sklearn import SklearnCV, SupportedSplitter


def __getattr__(name: str) -> object:
    """Load the CV bridge lazily to keep the core frame boundary acyclic."""

    if name in {"SklearnCV", "SupportedSplitter", "as_sklearn_cv"}:
        from lacuna.adapters import sklearn

        return getattr(sklearn, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "AdaptedFrame",
    "AvailabilityPolicy",
    "BacktestArtifactKind",
    "BacktestSchema",
    "BacktestSemantics",
    "FrameSummary",
    "PolarsFrame",
    "RevisionPolicy",
    "SklearnCV",
    "SupportedSplitter",
    "VendorSchema",
    "adapt_backtest",
    "adapt_vendor",
    "as_sklearn_cv",
    "frame_summary",
    "from_duckdb",
    "require_columns",
    "to_polars",
]
