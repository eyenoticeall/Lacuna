"""Immutable, JSON-serializable result and finding contracts."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
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

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> AnalysisResult:
        """Parse the strict supported v1 result envelope without executing content."""

        if cls is not AnalysisResult:
            raise TypeError("AnalysisResult.from_dict does not construct subclasses")
        return _analysis_result_from_dict(value)

    @classmethod
    def from_json(cls, value: str) -> AnalysisResult:
        """Parse strict finite JSON with duplicate-key rejection into a v1 result."""

        if cls is not AnalysisResult:
            raise TypeError("AnalysisResult.from_json does not construct subclasses")
        if not isinstance(value, str):
            raise TypeError("result JSON must be a string")

        def reject_constant(constant: str) -> object:
            raise ValueError(f"result JSON contains non-finite constant {constant!r}")

        def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, item in pairs:
                if key in result:
                    raise ValueError(f"result JSON contains duplicate object key {key!r}")
                result[key] = item
            return result

        try:
            parsed = json.loads(
                value,
                parse_constant=reject_constant,
                object_pairs_hook=unique_object,
            )
        except json.JSONDecodeError as error:
            raise ValueError(f"invalid result JSON: {error.msg}") from error
        if not isinstance(parsed, Mapping):
            raise ValueError("result JSON must contain an object at the top level")
        return _analysis_result_from_dict(parsed)


def _strict_object(
    value: object,
    *,
    name: str,
    required: set[str],
) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise ValueError(f"{name} keys must be strings")
    typed = cast(Mapping[str, object], value)
    observed = set(typed)
    missing = sorted(required - observed)
    extra = sorted(observed - required)
    if missing or extra:
        raise ValueError(f"{name} fields do not match v1: missing={missing}, unexpected={extra}")
    return typed


def _positive_integer(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return int(value)


def _optional_non_negative_integer(value: object, *, name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, Integral) or value < 0:
        raise ValueError(f"{name} must be null or a non-negative integer")
    return int(value)


def _analysis_result_from_dict(value: Mapping[str, object]) -> AnalysisResult:
    payload = _strict_object(
        value,
        name="result",
        required={"schema_version", "metadata", "metrics", "findings", "tables", "warnings"},
    )
    if payload["schema_version"] != "1":
        raise ValueError(f"unsupported result schema version {payload['schema_version']!r}")
    metadata_payload = _strict_object(
        payload["metadata"],
        name="result metadata",
        required={
            "method",
            "method_version",
            "parameters",
            "seed",
            "input_fingerprint",
            "created_at",
        },
    )
    method = metadata_payload["method"]
    if not isinstance(method, str) or not method:
        raise ValueError("result metadata method must be a non-empty string")
    parameters = metadata_payload["parameters"]
    if not isinstance(parameters, Mapping):
        raise ValueError("result metadata parameters must be an object")
    fingerprint = metadata_payload["input_fingerprint"]
    if fingerprint is not None and (not isinstance(fingerprint, str) or not fingerprint):
        raise ValueError("result input_fingerprint must be null or a non-empty string")
    created_at_raw = metadata_payload["created_at"]
    if not isinstance(created_at_raw, str) or not created_at_raw.endswith("Z"):
        raise ValueError("result created_at must be a UTC ISO 8601 string ending in Z")
    try:
        created_at = datetime.fromisoformat(created_at_raw[:-1] + "+00:00")
    except ValueError as error:
        raise ValueError("result created_at must be a valid UTC ISO 8601 timestamp") from error

    findings_raw = payload["findings"]
    if not isinstance(findings_raw, Sequence) or isinstance(findings_raw, str | bytes):
        raise ValueError("result findings must be an array")
    findings: list[Finding] = []
    for index, raw_finding in enumerate(findings_raw):
        item = _strict_object(
            raw_finding,
            name=f"result finding {index}",
            required={"code", "title", "message", "state", "severity", "category", "evidence"},
        )
        strings = {}
        for key in ("code", "title", "message", "category"):
            item_value = item[key]
            if not isinstance(item_value, str) or not item_value:
                raise ValueError(f"result finding {index} {key} must be a non-empty string")
            strings[key] = item_value
        state_raw = item["state"]
        try:
            state = FindingState(state_raw) if isinstance(state_raw, str) else None
        except ValueError as error:
            raise ValueError(f"result finding {index} has an unsupported state") from error
        if state is None:
            raise ValueError(f"result finding {index} has an unsupported state")
        severity_raw = item["severity"]
        try:
            severity = Severity(severity_raw) if isinstance(severity_raw, str) else None
        except ValueError as error:
            raise ValueError(f"result finding {index} has an unsupported severity") from error
        if severity is None:
            raise ValueError(f"result finding {index} has an unsupported severity")
        evidence = item["evidence"]
        if not isinstance(evidence, Mapping):
            raise ValueError(f"result finding {index} evidence must be an object")
        findings.append(
            Finding(
                code=strings["code"],
                title=strings["title"],
                message=strings["message"],
                state=state,
                severity=severity,
                category=strings["category"],
                evidence=cast(Mapping[str, JsonValue], evidence),
            )
        )

    metrics = payload["metrics"]
    tables = payload["tables"]
    if not isinstance(metrics, Mapping) or not isinstance(tables, Mapping):
        raise ValueError("result metrics and tables must be objects")
    warnings_raw = payload["warnings"]
    if not isinstance(warnings_raw, Sequence) or isinstance(warnings_raw, str | bytes):
        raise ValueError("result warnings must be an array")
    if any(not isinstance(warning, str) or not warning for warning in warnings_raw):
        raise ValueError("result warnings must contain non-empty strings")
    return AnalysisResult(
        metadata=ResultMetadata(
            method=method,
            method_version=_positive_integer(
                metadata_payload["method_version"], name="result method_version"
            ),
            parameters=cast(Mapping[str, JsonValue], parameters),
            seed=_optional_non_negative_integer(metadata_payload["seed"], name="result seed"),
            input_fingerprint=fingerprint,
            created_at=created_at,
        ),
        metrics=cast(Mapping[str, JsonValue], metrics),
        findings=tuple(findings),
        tables=cast(Mapping[str, JsonValue], tables),
        warnings=cast(tuple[str, ...], tuple(warnings_raw)),
        schema_version="1",
    )
