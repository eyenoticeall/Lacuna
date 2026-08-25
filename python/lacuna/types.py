"""Immutable, JSON-serializable result and finding contracts."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import Enum, StrEnum
from numbers import Integral, Real
from types import MappingProxyType
from typing import TypeAlias, cast

JsonScalar: TypeAlias = bool | int | float | str | None
JsonValue: TypeAlias = JsonScalar | tuple["JsonValue", ...] | Mapping[str, "JsonValue"]


def _freeze(value: object) -> JsonValue:
    if isinstance(value, Enum):
        return _freeze(value.value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("result datetimes must be timezone-aware")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if value is None or isinstance(value, bool | str):
        return value
    if isinstance(value, Integral):
        return int(value)
    if isinstance(value, Real):
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ValueError("result values must not contain NaN or infinity")
        return numeric
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("result mapping keys must be strings")
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze(item) for item in value)
    msg = f"result values must be JSON-compatible, received {type(value).__name__}"
    raise TypeError(msg)


def _thaw(value: JsonValue) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _freeze_mapping(value: Mapping[str, JsonValue]) -> Mapping[str, JsonValue]:
    frozen = _freeze(value)
    if not isinstance(frozen, Mapping):  # pragma: no cover - guaranteed by the input type
        raise TypeError("expected a JSON-compatible mapping")
    return frozen


class FindingState(StrEnum):
    """Outcome of an audit check."""

    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class Severity(StrEnum):
    """Materiality of a finding, independent of its state."""

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class ResultMetadata:
    """Provenance attached to a computed result."""

    method: str
    method_version: int = 1
    parameters: Mapping[str, JsonValue] = field(default_factory=dict)
    seed: int | None = None
    input_fingerprint: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not self.method:
            raise ValueError("method must not be empty")
        if self.method_version < 1:
            raise ValueError("method_version must be positive")
        if self.seed is not None and self.seed < 0:
            raise ValueError("seed must be non-negative")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        object.__setattr__(
            self, "parameters", cast(Mapping[str, JsonValue], _freeze(self.parameters))
        )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""

        return {
            "method": self.method,
            "method_version": self.method_version,
            "parameters": _thaw(self.parameters),
            "seed": self.seed,
            "input_fingerprint": self.input_fingerprint,
            "created_at": self.created_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        }


@dataclass(frozen=True, slots=True)
class Finding:
    """A single explicit piece of audit evidence."""

    code: str
    title: str
    message: str
    state: FindingState
    severity: Severity = Severity.INFO
    category: str = "general"
    evidence: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.code or not self.title or not self.message:
            raise ValueError("code, title, and message must not be empty")
        object.__setattr__(self, "evidence", cast(Mapping[str, JsonValue], _freeze(self.evidence)))

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""

        return {
            "code": self.code,
            "title": self.title,
            "message": self.message,
            "state": self.state.value,
            "severity": self.severity.value,
            "category": self.category,
            "evidence": _thaw(self.evidence),
        }


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    """Versioned structured output shared by future analysis modules."""

    metadata: ResultMetadata
    metrics: Mapping[str, JsonValue] = field(default_factory=dict)
    findings: tuple[Finding, ...] = ()
    tables: Mapping[str, JsonValue] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    schema_version: str = "1"

    def __post_init__(self) -> None:
        if not self.schema_version:
            raise ValueError("schema_version must not be empty")
        object.__setattr__(self, "metrics", cast(Mapping[str, JsonValue], _freeze(self.metrics)))
        if any(not isinstance(finding, Finding) for finding in self.findings):
            raise TypeError("findings must contain Finding values")
        object.__setattr__(self, "findings", tuple(self.findings))
        object.__setattr__(self, "tables", cast(Mapping[str, JsonValue], _freeze(self.tables)))
        if any(not isinstance(warning, str) or not warning for warning in self.warnings):
            raise ValueError("warnings must contain non-empty strings")
        object.__setattr__(self, "warnings", tuple(self.warnings))

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""

        return {
            "schema_version": self.schema_version,
            "metadata": self.metadata.to_dict(),
            "metrics": _thaw(self.metrics),
            "findings": [finding.to_dict() for finding in self.findings],
            "tables": _thaw(self.tables),
            "warnings": list(self.warnings),
        }

    def table(self, name: str) -> object:
        """Return the thawed source data for a named result table."""

        try:
            table = self.tables[name]
        except KeyError as error:
            available = ", ".join(sorted(self.tables)) or "none"
            raise KeyError(
                f"unknown result table {name!r}; available tables: {available}"
            ) from error
        return _thaw(table)

    def to_json(self, *, indent: int | None = 2) -> str:
        """Serialize the result without unsafe Python object serialization."""

        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)
