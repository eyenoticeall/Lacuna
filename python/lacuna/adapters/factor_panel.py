"""Generic ingestion for explicitly described factor-research panels."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from types import MappingProxyType
from typing import cast

import polars as pl

from lacuna.adapters.types import AdaptedFrame, normalize_mapped_frame
from lacuna.exceptions import DataContractError, MethodContractError
from lacuna.types import (
    AnalysisResult,
    Finding,
    FindingState,
    JsonValue,
    ResultMetadata,
    Severity,
)

_REQUIRED = ("observation_time", "instrument", "signal")
_OPTIONAL = (
    "forward_return",
    "horizon",
    "group",
    "bucket",
    "available_time",
    "entry_time",
    "label_end",
)
_SUPPORTED = frozenset((*_REQUIRED, *_OPTIONAL))


@dataclass(frozen=True, slots=True)
class FactorPanelSemantics:
    """Research semantics that Lacuna refuses to infer from a factor panel."""

    signal_observation: str
    decision_time_rule: str
    forward_return_entry: str
    forward_return_exit: str
    horizon_clock: str
    timezone: str
    calendar: str
    adjustment_policy: str
    group_availability: str
    imported_bucket_definition: str

    def __post_init__(self) -> None:
        values = asdict(self)
        invalid = sorted(
            name
            for name, value in values.items()
            if not isinstance(value, str) or not value.strip()
        )
        if invalid:
            raise MethodContractError(
                "factor-panel semantics must be non-empty strings: " + ", ".join(invalid)
            )


@dataclass(frozen=True, slots=True)
class FactorPanelSchema:
    """Immutable canonical-to-source mapping for a generic factor panel."""

    schema_id: str
    columns: Mapping[str, str]
    semantics: FactorPanelSemantics
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.schema_id, str) or not self.schema_id:
            raise MethodContractError("schema_id must not be empty")
        if (
            isinstance(self.schema_version, bool)
            or not isinstance(self.schema_version, int)
            or self.schema_version < 1
        ):
            raise MethodContractError("schema_version must be a positive integer")
        if not isinstance(self.semantics, FactorPanelSemantics):
            raise MethodContractError("semantics must be FactorPanelSemantics")
        if not isinstance(self.columns, Mapping):
            raise MethodContractError("columns must be a canonical-to-source mapping")
        if any(
            not isinstance(canonical, str)
            or not canonical
            or not isinstance(source, str)
            or not source
            for canonical, source in self.columns.items()
        ):
            raise MethodContractError("column mappings must use non-empty string names")
        unknown = sorted(set(self.columns).difference(_SUPPORTED))
        if unknown:
            raise MethodContractError(
                "unsupported factor-panel canonical fields: " + ", ".join(unknown)
            )
        missing = sorted(set(_REQUIRED).difference(self.columns))
        if missing:
            raise MethodContractError(
                "factor-panel schema is missing canonical mappings: " + ", ".join(missing)
            )
        if len(set(self.columns.values())) != len(self.columns):
            raise MethodContractError("factor-panel source columns must map uniquely")
        object.__setattr__(self, "columns", MappingProxyType(dict(self.columns)))


def _pandas_index_levels(data: object) -> tuple[str, ...]:
    if type(data).__module__.split(".", maxsplit=1)[0] != "pandas":
        return ()
    index = getattr(data, "index", None)
    raw_names = getattr(index, "names", ())
    return tuple(name for name in raw_names if isinstance(name, str) and name)


def _copy_classification(data: object, frame: pl.DataFrame | pl.LazyFrame) -> str:
    if isinstance(data, pl.LazyFrame) and isinstance(frame, pl.DataFrame):
        return "materializing"
    if isinstance(data, pl.DataFrame | pl.LazyFrame):
        return "potentially_zero_copy"
    if type(data).__module__.split(".", maxsplit=1)[0] == "pandas":
        return "one_copy"
    if hasattr(data, "__arrow_c_stream__"):
        return "potentially_zero_copy"
    return "one_copy"


def adapt_factor_panel(
    data: object,
    schema: FactorPanelSchema,
    *,
    collect: bool = False,
) -> AdaptedFrame:
    """Normalize a factor panel without performing research methodology."""

    if not isinstance(schema, FactorPanelSchema):
        raise MethodContractError("schema must be a FactorPanelSchema")
    index_levels = _pandas_index_levels(data)
    mapped_index_levels = tuple(
        source for source in schema.columns.values() if source in index_levels
    )
    try:
        frame, original_columns = normalize_mapped_frame(
            data,
            columns=schema.columns,
            required=_REQUIRED,
            collect=collect,
            include_pandas_index=bool(mapped_index_levels),
        )
    except (TypeError, ValueError) as error:
        raise DataContractError(f"factor-panel normalization failed: {error}") from error

    physical_schema = frame.collect_schema()
    if not physical_schema["signal"].is_numeric():
        raise DataContractError("canonical signal must use a numeric dtype")
    for column in ("forward_return",):
        if column in physical_schema and not physical_schema[column].is_numeric():
            raise DataContractError(f"canonical {column} must use a numeric dtype")
    if "bucket" in physical_schema and not physical_schema["bucket"].is_integer():
        raise DataContractError("canonical bucket must use an integer dtype")

    normalized_columns = tuple(physical_schema.names())
    semantics = cast(dict[str, JsonValue], asdict(schema.semantics))
    unknown_semantics = tuple(
        {"semantic": name, "value": value}
        for name, value in semantics.items()
        if isinstance(value, str) and value.casefold() == "unknown"
    )
    findings: list[Finding] = []
    if unknown_semantics:
        findings.append(
            Finding(
                code="FACTOR_PANEL_SEMANTICS_UNKNOWN",
                title="Factor-panel semantics are incomplete",
                message=(
                    "Unknown timing or classification semantics remain unknown; adaptation does "
                    "not convert them into a point-in-time safety claim."
                ),
                state=FindingState.UNKNOWN,
                severity=Severity.MEDIUM,
                category="temporal_integrity",
                evidence={"unknown_fields": tuple(row["semantic"] for row in unknown_semantics)},
            )
        )

    mapping_rows: tuple[JsonValue, ...] = tuple(
        {
            "canonical": canonical,
            "source": source,
            "required": canonical in _REQUIRED,
            "source_location": "pandas_index" if source in mapped_index_levels else "column",
        }
        for canonical, source in sorted(schema.columns.items())
    )
    source_type = f"{type(data).__module__}.{type(data).__name__}"
    input_lazy = isinstance(data, pl.LazyFrame)
    materialized = isinstance(frame, pl.DataFrame)
    evidence = AnalysisResult(
        metadata=ResultMetadata(
            method="adapters.factor_panel",
            method_version=1,
            parameters={
                "schema_id": schema.schema_id,
                "schema_version": schema.schema_version,
                "source_type": source_type,
                "semantics": semantics,
                "mapped_pandas_index_levels": mapped_index_levels,
                "lazy_input": input_lazy,
                "materialized": materialized,
                "materialization_reason": (
                    "explicit_collect" if input_lazy and materialized else None
                ),
                "adapter_copy": _copy_classification(data, frame),
                "adapter_operations": (
                    "include_explicit_pandas_index_levels",
                    "explicit_column_rename",
                )
                if mapped_index_levels
                else ("explicit_column_rename",),
                "methodology_executed": False,
                "row_order_preserved": True,
                "extra_columns_preserved": True,
            },
        ),
        metrics={
            "source_column_count": len(original_columns),
            "normalized_column_count": len(normalized_columns),
            "row_count": frame.height if isinstance(frame, pl.DataFrame) else None,
            "unknown_semantics": len(unknown_semantics),
        },
        findings=tuple(findings),
        tables={
            "column_mapping": mapping_rows,
            "unknown_semantics": cast(tuple[JsonValue, ...], unknown_semantics),
        },
        warnings=(
            "Factor-panel semantics are caller declarations; Lacuna performs no filtering, "
            "joining, bucketing, label construction, or statistical analysis in this adapter.",
        ),
    )
    return AdaptedFrame(frame=frame, evidence=evidence)


__all__ = ["FactorPanelSchema", "FactorPanelSemantics", "adapt_factor_panel"]
