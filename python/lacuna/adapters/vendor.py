"""Versioned schemas for licensed or proprietary vendor datasets."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, cast

import polars as pl

from lacuna.adapters.types import AdaptedFrame, normalize_mapped_frame
from lacuna.exceptions import DataContractError, MethodContractError
from lacuna.types import AnalysisResult, JsonValue, ResultMetadata

AvailabilityPolicy = Literal["point_in_time", "latest_only", "unknown"]
RevisionPolicy = Literal["versioned", "latest_only", "not_applicable", "unknown"]


@dataclass(frozen=True, slots=True)
class VendorSchema:
    """Explicit mapping and temporal semantics for one vendor dataset version."""

    schema_id: str
    columns: Mapping[str, str]
    required: tuple[str, ...]
    schema_version: int = 1
    availability: AvailabilityPolicy = "unknown"
    revisions: RevisionPolicy = "unknown"
    timezone: str | None = None
    timezone_columns: tuple[str, ...] = ()
    price_adjustment: str | None = None
    identifier_policy: str = "vendor_native"

    def __post_init__(self) -> None:
        if not isinstance(self.schema_id, str) or not self.schema_id:
            raise MethodContractError("schema_id must not be empty")
        if (
            isinstance(self.schema_version, bool)
            or not isinstance(self.schema_version, int)
            or self.schema_version < 1
        ):
            raise MethodContractError("schema_version must be a positive integer")
        if not isinstance(self.columns, Mapping):
            raise MethodContractError("columns must be a canonical-to-source mapping")
        if not isinstance(self.required, tuple):
            raise MethodContractError("required must be a tuple of canonical column names")
        if self.availability not in {"point_in_time", "latest_only", "unknown"}:
            raise MethodContractError("unsupported vendor availability policy")
        if self.revisions not in {"versioned", "latest_only", "not_applicable", "unknown"}:
            raise MethodContractError("unsupported vendor revision policy")
        if self.timezone is not None and (not isinstance(self.timezone, str) or not self.timezone):
            raise MethodContractError("timezone must be a non-empty IANA name when supplied")
        if not isinstance(self.identifier_policy, str) or not self.identifier_policy:
            raise MethodContractError("identifier_policy must not be empty")
        if self.price_adjustment is not None and (
            not isinstance(self.price_adjustment, str) or not self.price_adjustment
        ):
            raise MethodContractError("price_adjustment must not be empty when supplied")
        if not isinstance(self.timezone_columns, tuple):
            raise MethodContractError("timezone_columns must be a tuple of canonical names")
        if any(not isinstance(column, str) or not column for column in self.required):
            raise MethodContractError("required must contain non-empty canonical names")
        if any(not isinstance(column, str) or not column for column in self.timezone_columns):
            raise MethodContractError("timezone_columns must contain non-empty canonical names")
        if len(set(self.required)) != len(self.required):
            raise MethodContractError("required canonical columns must be unique")
        if len(set(self.timezone_columns)) != len(self.timezone_columns):
            raise MethodContractError("timezone_columns must be unique")
        unknown_timezone = sorted(set(self.timezone_columns).difference(self.columns))
        if unknown_timezone:
            raise MethodContractError(
                f"timezone columns are not mapped: {', '.join(unknown_timezone)}"
            )
        if self.availability == "point_in_time" and "available_time" not in self.columns:
            raise MethodContractError(
                "point_in_time vendor schemas must map the canonical available_time column"
            )
        if self.revisions == "versioned" and not {
            "revision_time",
            "revision_id",
        }.intersection(self.columns):
            raise MethodContractError(
                "versioned vendor schemas must map revision_time or revision_id"
            )
        # Copy caller-owned mappings so later mutation cannot change semantics.
        object.__setattr__(self, "columns", MappingProxyType(dict(self.columns)))
        # Run shared structural validation without needing an input frame.
        if not self.columns:
            raise MethodContractError("columns must contain at least one mapping")
        if any(
            not isinstance(key, str) or not key or not isinstance(value, str) or not value
            for key, value in self.columns.items()
        ):
            raise MethodContractError("column mappings must use non-empty names")
        if len(set(self.columns.values())) != len(self.columns):
            raise MethodContractError("vendor source columns must map uniquely")
        unknown_required = sorted(set(self.required).difference(self.columns))
        if unknown_required:
            raise MethodContractError(
                f"required canonical columns are not mapped: {', '.join(unknown_required)}"
            )


def _validate_timezones(frame: pl.DataFrame | pl.LazyFrame, schema: VendorSchema) -> None:
    if not schema.timezone_columns:
        return
    physical_schema = frame.collect_schema()
    for column in schema.timezone_columns:
        dtype = physical_schema[column]
        observed = getattr(dtype, "time_zone", None)
        if observed is None:
            raise DataContractError(f"vendor timestamp column {column!r} must be timezone-aware")
        if schema.timezone is not None and observed != schema.timezone:
            raise DataContractError(
                f"vendor timestamp column {column!r} uses timezone {observed!r}, "
                f"expected {schema.timezone!r}"
            )


def adapt_vendor(
    data: object,
    schema: VendorSchema,
    *,
    collect: bool = False,
) -> AdaptedFrame:
    """Apply a declared vendor mapping without hiding temporal assumptions."""

    if not isinstance(schema, VendorSchema):
        raise MethodContractError("schema must be a VendorSchema")
    source_type = f"{type(data).__module__}.{type(data).__name__}"
    frame, original_columns = normalize_mapped_frame(
        data,
        columns=schema.columns,
        required=schema.required,
        collect=collect,
    )
    _validate_timezones(frame, schema)
    normalized_columns = (
        tuple(frame.collect_schema().names())
        if isinstance(frame, pl.LazyFrame)
        else tuple(frame.columns)
    )
    mapping_rows: tuple[dict[str, JsonValue], ...] = tuple(
        {
            "canonical": canonical,
            "source": source,
            "required": canonical in schema.required,
        }
        for canonical, source in sorted(schema.columns.items())
    )
    evidence = AnalysisResult(
        metadata=ResultMetadata(
            method="adapters.vendor_schema",
            method_version=1,
            parameters={
                "schema_id": schema.schema_id,
                "schema_version": schema.schema_version,
                "source_type": source_type,
                "availability": schema.availability,
                "revisions": schema.revisions,
                "timezone": schema.timezone,
                "timezone_columns": schema.timezone_columns,
                "price_adjustment": schema.price_adjustment,
                "identifier_policy": schema.identifier_policy,
                "materialized": isinstance(frame, pl.DataFrame),
                "transformations": ("explicit_column_rename",),
            },
        ),
        metrics={
            "source_column_count": len(original_columns),
            "normalized_column_count": len(normalized_columns),
            "row_count": frame.height if isinstance(frame, pl.DataFrame) else None,
        },
        tables={"column_mapping": cast(tuple[JsonValue, ...], mapping_rows)},
        warnings=(
            "Vendor timestamps and archive completeness are declarations supplied by the caller; "
            "Lacuna does not independently certify them.",
        ),
    )
    return AdaptedFrame(frame=frame, evidence=evidence)


__all__ = [
    "AvailabilityPolicy",
    "RevisionPolicy",
    "VendorSchema",
    "adapt_vendor",
]
