"""Framework-neutral ingestion for explicit backtest artifacts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from types import MappingProxyType
from typing import Literal, cast

import polars as pl

from lacuna.adapters.types import AdaptedFrame, normalize_mapped_frame
from lacuna.exceptions import MethodContractError
from lacuna.types import AnalysisResult, JsonValue, ResultMetadata

BacktestArtifactKind = Literal["returns", "trades", "positions"]

_REQUIRED_COLUMNS: dict[BacktestArtifactKind, tuple[str, ...]] = {
    "returns": ("time", "strategy", "return"),
    "trades": (
        "decision_time",
        "execution_time",
        "instrument",
        "side",
        "quantity",
        "price",
    ),
    "positions": ("time", "instrument", "position"),
}


@dataclass(frozen=True, slots=True)
class BacktestSemantics:
    """Backtester assumptions that must accompany imported artifacts."""

    returns: Literal["gross", "net"]
    return_frequency: str
    compounding: Literal["simple", "log"]
    position_timing: str
    execution_delay: str
    price_field: str
    price_adjustment: str
    costs: Literal["included", "excluded"]
    borrow: Literal["included", "excluded", "not_applicable"]
    timezone: str
    calendar: str
    session: str
    missing_instruments: str
    delistings: str

    def __post_init__(self) -> None:
        if self.returns not in {"gross", "net"}:
            raise MethodContractError("returns must be 'gross' or 'net'")
        if self.compounding not in {"simple", "log"}:
            raise MethodContractError("compounding must be 'simple' or 'log'")
        if self.costs not in {"included", "excluded"}:
            raise MethodContractError("costs must be 'included' or 'excluded'")
        if self.borrow not in {"included", "excluded", "not_applicable"}:
            raise MethodContractError("unsupported borrow treatment")
        named = {
            "return_frequency": self.return_frequency,
            "position_timing": self.position_timing,
            "execution_delay": self.execution_delay,
            "price_field": self.price_field,
            "price_adjustment": self.price_adjustment,
            "timezone": self.timezone,
            "calendar": self.calendar,
            "session": self.session,
            "missing_instruments": self.missing_instruments,
            "delistings": self.delistings,
        }
        empty = sorted(name for name, value in named.items() if not value)
        if empty:
            raise MethodContractError(f"backtest semantics must not be empty: {', '.join(empty)}")


@dataclass(frozen=True, slots=True)
class BacktestSchema:
    """Canonical field mapping for one framework/artifact contract."""

    schema_id: str
    artifact: BacktestArtifactKind
    columns: Mapping[str, str]
    semantics: BacktestSemantics
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.schema_id, str) or not self.schema_id:
            raise MethodContractError("schema_id must not be empty")
        if self.artifact not in _REQUIRED_COLUMNS:
            raise MethodContractError("artifact must be returns, trades, or positions")
        if not isinstance(self.semantics, BacktestSemantics):
            raise MethodContractError("semantics must be BacktestSemantics")
        if (
            isinstance(self.schema_version, bool)
            or not isinstance(self.schema_version, int)
            or self.schema_version < 1
        ):
            raise MethodContractError("schema_version must be a positive integer")
        if not isinstance(self.columns, Mapping):
            raise MethodContractError("columns must be a canonical-to-source mapping")
        if any(
            not isinstance(key, str) or not key or not isinstance(value, str) or not value
            for key, value in self.columns.items()
        ):
            raise MethodContractError("column mappings must use non-empty names")
        if len(set(self.columns.values())) != len(self.columns):
            raise MethodContractError("backtest source columns must map uniquely")
        missing = sorted(set(_REQUIRED_COLUMNS[self.artifact]).difference(self.columns))
        if missing:
            raise MethodContractError(
                f"{self.artifact} schema is missing canonical mappings: {', '.join(missing)}"
            )
        object.__setattr__(self, "columns", MappingProxyType(dict(self.columns)))


def adapt_backtest(
    data: object,
    schema: BacktestSchema,
    *,
    collect: bool = False,
) -> AdaptedFrame:
    """Normalize one backtest artifact while preserving all declared assumptions."""

    if not isinstance(schema, BacktestSchema):
        raise MethodContractError("schema must be a BacktestSchema")
    required = _REQUIRED_COLUMNS[schema.artifact]
    source_type = f"{type(data).__module__}.{type(data).__name__}"
    frame, original_columns = normalize_mapped_frame(
        data,
        columns=schema.columns,
        required=required,
        collect=collect,
    )
    normalized_columns = (
        tuple(frame.collect_schema().names())
        if isinstance(frame, pl.LazyFrame)
        else tuple(frame.columns)
    )
    mapping_rows: tuple[dict[str, JsonValue], ...] = tuple(
        {
            "canonical": canonical,
            "source": source,
            "required": canonical in required,
        }
        for canonical, source in sorted(schema.columns.items())
    )
    semantics = cast(dict[str, JsonValue], asdict(schema.semantics))
    evidence = AnalysisResult(
        metadata=ResultMetadata(
            method="adapters.backtest_artifact",
            method_version=1,
            parameters={
                "schema_id": schema.schema_id,
                "schema_version": schema.schema_version,
                "artifact": schema.artifact,
                "source_type": source_type,
                "semantics": semantics,
                "materialized": isinstance(frame, pl.DataFrame),
                "methodology_executed": False,
            },
        ),
        metrics={
            "source_column_count": len(original_columns),
            "normalized_column_count": len(normalized_columns),
            "row_count": frame.height if isinstance(frame, pl.DataFrame) else None,
        },
        tables={"column_mapping": cast(tuple[JsonValue, ...], mapping_rows)},
    )
    return AdaptedFrame(frame=frame, evidence=evidence)


__all__ = [
    "BacktestArtifactKind",
    "BacktestSchema",
    "BacktestSemantics",
    "adapt_backtest",
]
