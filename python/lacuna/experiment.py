"""Append-only experiment lineage and canonical research identities."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import threading
import uuid
import weakref
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import Enum, StrEnum
from io import StringIO
from numbers import Integral, Real
from pathlib import Path
from types import MappingProxyType
from typing import cast

import numpy as np
import polars as pl

from lacuna.exceptions import DataContractError, MethodContractError
from lacuna.types import AnalysisResult, Finding, FindingState, JsonValue, ResultMetadata, Severity

CANONICALIZATION_VERSION = 1
REGISTRY_SCHEMA_VERSION = 1
_SENSITIVE_KEYS = {
    "access_key",
    "api_key",
    "authorization",
    "cookie",
    "credential",
    "password",
    "secret",
    "token",
}
_STREAM_BATCH_TARGET_BYTES = 1024 * 1024


class AttemptStatus(StrEnum):
    """Terminal status of one immutable execution attempt."""

    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


def _is_sensitive_key(key: str) -> bool:
    normalized = key.casefold().replace("-", "_")
    return normalized in _SENSITIVE_KEYS or any(
        normalized.endswith(f"_{suffix}") for suffix in _SENSITIVE_KEYS
    )


def _canonicalize(value: object, *, path: str = "$") -> object:
    if isinstance(value, Enum):
        return _canonicalize(value.value, path=path)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise DataContractError(f"{path} contains a timezone-naive datetime")
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
            raise DataContractError(f"{path} contains NaN or infinity")
        return 0.0 if numeric == 0.0 else numeric
    if isinstance(value, Mapping):
        normalized: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise DataContractError(f"{path} contains a non-string mapping key")
            if _is_sensitive_key(key):
                raise DataContractError(
                    f"{path}.{key} looks credential-bearing and is not recorded"
                )
            normalized[key] = _canonicalize(item, path=f"{path}.{key}")
        return {key: normalized[key] for key in sorted(normalized)}
    if isinstance(value, list | tuple):
        return [_canonicalize(item, path=f"{path}[{index}]") for index, item in enumerate(value)]
    if isinstance(value, set | frozenset):
        raise DataContractError(f"{path} contains an unordered set")
    if callable(value):
        raise DataContractError(f"{path} contains an opaque callable")
    raise DataContractError(f"{path} contains unsupported value type {type(value).__name__}")


def _validate_canonical(value: object, *, path: str = "$") -> None:
    """Validate c14n-v1 in legacy traversal order without constructing a normalized tree."""

    if isinstance(value, np.generic):
        _validate_canonical(value.item(), path=path)
        return
    if isinstance(value, Enum):
        _validate_canonical(value.value, path=path)
        return
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise DataContractError(f"{path} contains a timezone-naive datetime")
        return
    if isinstance(value, date | bool | str | Integral) or value is None:
        return
    if isinstance(value, Real):
        if not math.isfinite(float(value)):
            raise DataContractError(f"{path} contains NaN or infinity")
        return
    if isinstance(value, pl.DataFrame):
        for index, row in enumerate(value.iter_rows(named=True)):
            _validate_canonical(row, path=f"{path}[{index}]")
        return
    if isinstance(value, pl.Series):
        for index, item in enumerate(value):
            _validate_canonical(item, path=f"{path}[{index}]")
        return
    if isinstance(value, np.ndarray):
        if value.ndim == 0:
            _validate_canonical(value.item(), path=path)
            return
        if value.dtype.kind in "biuU":
            return
        if value.dtype.kind == "f":
            nonfinite = ~np.isfinite(value)
            if bool(nonfinite.any()):
                first = tuple(int(index) for index in np.argwhere(nonfinite)[0])
                location = "".join(f"[{index}]" for index in first)
                raise DataContractError(f"{path}{location} contains NaN or infinity")
            return
        for index, item in enumerate(value):
            _validate_canonical(item, path=f"{path}[{index}]")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise DataContractError(f"{path} contains a non-string mapping key")
            if _is_sensitive_key(key):
                raise DataContractError(
                    f"{path}.{key} looks credential-bearing and is not recorded"
                )
            _validate_canonical(item, path=f"{path}.{key}")
        return
    if isinstance(value, list | tuple):
        for index, item in enumerate(value):
            _validate_canonical(item, path=f"{path}[{index}]")
        return
    if isinstance(value, set | frozenset):
        raise DataContractError(f"{path} contains an unordered set")
    if callable(value):
        raise DataContractError(f"{path} contains an opaque callable")
    raise DataContractError(f"{path} contains unsupported value type {type(value).__name__}")


def _scalar_chunk(value: object) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _normalized_json(value: object) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _iter_batched_list_chunks(values: Iterator[object]) -> Iterator[str]:
    yield "["
    first = True
    for batch in values:
        encoded = _normalized_json(batch)
        interior = encoded[1:-1]
        if not interior:
            continue
        if not first:
            yield ","
        yield interior
        first = False
    yield "]"


def _array_batches(value: np.ndarray, *, path: str) -> Iterator[object]:
    if len(value) == 0:
        return
    row_bytes = max(int(value[0].nbytes) if value.ndim > 1 else int(value.itemsize), 1)
    rows_per_batch = max(1, _STREAM_BATCH_TARGET_BYTES // row_bytes)
    for start in range(0, len(value), rows_per_batch):
        batch = value[start : start + rows_per_batch]
        if value.dtype.kind == "f":
            nonfinite = ~np.isfinite(batch)
            if bool(nonfinite.any()):
                first = tuple(int(index) for index in np.argwhere(nonfinite)[0])
                first = (first[0] + start, *first[1:])
                location = "".join(f"[{index}]" for index in first)
                raise DataContractError(f"{path}{location} contains NaN or infinity")
            batch = np.where(batch == 0, 0.0, batch)
            yield batch.tolist()
        elif value.dtype.kind in "biuU":
            yield batch.tolist()
        else:
            yield _canonicalize(batch.tolist())


def _frame_batches(value: pl.DataFrame) -> Iterator[object]:
    estimated_size = int(value.estimated_size())
    estimated_row_bytes = max(estimated_size // max(value.height, 1), 1)
    rows_per_batch = max(1, _STREAM_BATCH_TARGET_BYTES // estimated_row_bytes)
    for batch in value.iter_slices(n_rows=rows_per_batch):
        yield _canonicalize(batch.to_dicts())


def _iter_sequence_chunks(values: Iterable[object], *, path: str) -> Iterator[str]:
    yield "["
    for index, item in enumerate(values):
        if index:
            yield ","
        yield from _iter_canonical_chunks(item, path=f"{path}[{index}]")
    yield "]"


def _iter_canonical_chunks(value: object, *, path: str = "$") -> Iterator[str]:
    """Emit exact c14n-v1 text in bounded chunks after validation."""

    if isinstance(value, np.generic):
        yield from _iter_canonical_chunks(value.item(), path=path)
        return
    if isinstance(value, Enum):
        yield from _iter_canonical_chunks(value.value, path=path)
        return
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise DataContractError(f"{path} contains a timezone-naive datetime")
        yield _scalar_chunk(value.astimezone(UTC).isoformat().replace("+00:00", "Z"))
        return
    if isinstance(value, date):
        yield _scalar_chunk(value.isoformat())
        return
    if value is None or isinstance(value, bool | str):
        yield _scalar_chunk(value)
        return
    if isinstance(value, Integral):
        yield str(int(value))
        return
    if isinstance(value, Real):
        numeric = float(value)
        if not math.isfinite(numeric):
            raise DataContractError(f"{path} contains NaN or infinity")
        yield _scalar_chunk(0.0 if numeric == 0.0 else numeric)
        return
    if isinstance(value, pl.DataFrame):
        yield from _iter_batched_list_chunks(_frame_batches(value))
        return
    if isinstance(value, np.ndarray):
        if value.ndim == 0:
            yield from _iter_canonical_chunks(value.item(), path=path)
            return
        yield from _iter_batched_list_chunks(_array_batches(value, path=path))
        return
    if isinstance(value, pl.Series):
        yield from _iter_sequence_chunks(value, path=path)
        return
    if isinstance(value, Mapping):
        _validate_canonical(value, path=path)
        yield "{"
        for index, key in enumerate(sorted(value)):
            if index:
                yield ","
            yield _scalar_chunk(key)
            yield ":"
            yield from _iter_canonical_chunks(value[key], path=f"{path}.{key}")
        yield "}"
        return
    if isinstance(value, list | tuple):
        yield from _iter_sequence_chunks(value, path=path)
        return
    if isinstance(value, set | frozenset):
        raise DataContractError(f"{path} contains an unordered set")
    if callable(value):
        raise DataContractError(f"{path} contains an opaque callable")
    raise DataContractError(f"{path} contains unsupported value type {type(value).__name__}")


def _streaming_canonical_json(value: object) -> str:
    output = StringIO()
    output.writelines(_iter_canonical_chunks(value))
    return output.getvalue()


def _streaming_fingerprint(value: object, *, namespace: str) -> str:
    if not namespace or namespace.strip() != namespace:
        raise MethodContractError("fingerprint namespace must be a non-empty trimmed string")
    digest = hashlib.sha256()
    digest.update(f"lacuna:c14n:{CANONICALIZATION_VERSION}:{namespace}\0".encode())
    for chunk in _iter_canonical_chunks(value):
        digest.update(chunk.encode())
    return f"sha256:c14n-v{CANONICALIZATION_VERSION}:{digest.hexdigest()}"


def canonical_json(value: object) -> str:
    """Encode supported values with deterministic key, time, float, and sequence semantics."""

    return json.dumps(
        _canonicalize(value),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _contains_bulk_canonical_input(value: object) -> bool:
    if isinstance(value, np.ndarray | pl.DataFrame | pl.Series):
        return True
    if isinstance(value, Mapping):
        return any(_contains_bulk_canonical_input(item) for item in value.values())
    if isinstance(value, list | tuple):
        return any(_contains_bulk_canonical_input(item) for item in value)
    return False


def fingerprint(value: object, *, namespace: str) -> str:
    """Return a versioned SHA-256 identity over canonical JSON and an explicit namespace."""

    if not namespace or namespace.strip() != namespace:
        raise MethodContractError("fingerprint namespace must be a non-empty trimmed string")
    if _contains_bulk_canonical_input(value):
        return _streaming_fingerprint(value, namespace=namespace)
    payload = (
        f"lacuna:c14n:{CANONICALIZATION_VERSION}:{namespace}\0{canonical_json(value)}"
    ).encode()
    digest = hashlib.sha256(payload).hexdigest()
    return f"sha256:c14n-v{CANONICALIZATION_VERSION}:{digest}"


def _freeze_json(value: object) -> JsonValue:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return cast(JsonValue, value)


def _mapping_from_json(value: str) -> Mapping[str, JsonValue]:
    decoded = json.loads(value)
    if not isinstance(decoded, dict):
        raise RuntimeError("registry mapping payload is corrupt")
    return cast(Mapping[str, JsonValue], _freeze_json(decoded))


def _utc_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RuntimeError("registry timestamp is not timezone-aware")
    return parsed.astimezone(UTC)


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DataContractError("attempt timestamps must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class AttemptRecord:
    """One immutable attempt, including failures and retries."""

    sequence: int
    attempt_id: str
    trial_id: str
    family: str
    experiment: str
    created_at: datetime
    status: AttemptStatus
    parameters: Mapping[str, JsonValue]
    metric_name: str | None
    metric_value: float | None
    method: str
    method_version: int
    data_fingerprint: str | None
    code_fingerprint: str | None
    result_fingerprint: str | None
    error_category: str | None
    supersedes_attempt_id: str | None
    supersedes_reason: str | None
    metadata: Mapping[str, JsonValue]

    def to_dict(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "attempt_id": self.attempt_id,
            "trial_id": self.trial_id,
            "family": self.family,
            "experiment": self.experiment,
            "created_at": _utc_text(self.created_at),
            "status": self.status.value,
            "parameters": json.loads(canonical_json(self.parameters)),
            "metric_name": self.metric_name,
            "metric_value": self.metric_value,
            "method": self.method,
            "method_version": self.method_version,
            "data_fingerprint": self.data_fingerprint,
            "code_fingerprint": self.code_fingerprint,
            "result_fingerprint": self.result_fingerprint,
            "error_category": self.error_category,
            "supersedes_attempt_id": self.supersedes_attempt_id,
            "supersedes_reason": self.supersedes_reason,
            "metadata": json.loads(canonical_json(self.metadata)),
        }


@dataclass(frozen=True, slots=True)
class SelectionRecord:
    """An immutable selection decision over the complete eligible trial set."""

    sequence: int
    selection_id: str
    created_at: datetime
    eligible_trial_ids: tuple[str, ...]
    selected_trial_ids: tuple[str, ...]
    metric: str
    direction: str
    tie_breaking: str
    used_holdout: bool
    actor: str | None
    exclusion_reasons: Mapping[str, JsonValue]

    def to_dict(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "selection_id": self.selection_id,
            "created_at": _utc_text(self.created_at),
            "eligible_trial_ids": list(self.eligible_trial_ids),
            "selected_trial_ids": list(self.selected_trial_ids),
            "metric": self.metric,
            "direction": self.direction,
            "tie_breaking": self.tie_breaking,
            "used_holdout": self.used_holdout,
            "actor": self.actor,
            "exclusion_reasons": json.loads(canonical_json(self.exclusion_reasons)),
        }


_ATTEMPT_COLUMNS = """
sequence, attempt_id, trial_id, family, experiment, created_at, status,
parameters_json, metric_name, metric_value, method, method_version,
data_fingerprint, code_fingerprint, result_fingerprint, error_category,
supersedes_attempt_id, supersedes_reason, metadata_json
"""


class ExperimentRegistry:
    """Append-only SQLite registry for local experiment attempts and selections."""

    def __init__(
        self,
        name: str,
        *,
        path: str | Path | None = None,
        family: str | None = None,
    ) -> None:
        if not name or name.strip() != name:
            raise MethodContractError("registry name must be a non-empty trimmed string")
        resolved_family = family or name
        if not resolved_family or resolved_family.strip() != resolved_family:
            raise MethodContractError("family must be a non-empty trimmed string")
        self.name = name
        self.family = resolved_family
        self._lock = threading.RLock()
        self._path = Path(path) if path is not None else None
        if self._path is not None and not self._path.parent.exists():
            raise DataContractError(
                f"registry parent directory does not exist: {self._path.parent}"
            )
        database = ":memory:" if self._path is None else str(self._path)
        self._connection = sqlite3.connect(database, timeout=5.0, check_same_thread=False)
        self._finalizer = weakref.finalize(self, self._connection.close)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA busy_timeout = 5000")
        if self._path is not None:
            self._connection.execute("PRAGMA journal_mode = WAL")
        self._initialize()

    def _initialize(self) -> None:
        with self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS registry_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS attempts (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    attempt_id TEXT NOT NULL UNIQUE,
                    trial_id TEXT NOT NULL,
                    family TEXT NOT NULL,
                    experiment TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('completed', 'failed', 'cancelled')),
                    parameters_json TEXT NOT NULL,
                    metric_name TEXT,
                    metric_value REAL,
                    method TEXT NOT NULL,
                    method_version INTEGER NOT NULL CHECK(method_version >= 1),
                    data_fingerprint TEXT,
                    code_fingerprint TEXT,
                    result_fingerprint TEXT,
                    error_category TEXT,
                    supersedes_attempt_id TEXT,
                    supersedes_reason TEXT,
                    metadata_json TEXT NOT NULL,
                    FOREIGN KEY(supersedes_attempt_id) REFERENCES attempts(attempt_id)
                );
                CREATE INDEX IF NOT EXISTS attempts_trial_id ON attempts(trial_id);
                CREATE TABLE IF NOT EXISTS selections (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    selection_id TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    eligible_trial_ids_json TEXT NOT NULL,
                    selected_trial_ids_json TEXT NOT NULL,
                    metric TEXT NOT NULL,
                    direction TEXT NOT NULL CHECK(direction IN ('maximize', 'minimize')),
                    tie_breaking TEXT NOT NULL,
                    used_holdout INTEGER NOT NULL CHECK(used_holdout IN (0, 1)),
                    actor TEXT,
                    exclusion_reasons_json TEXT NOT NULL
                );
                """
            )
            expected = {
                "schema_version": str(REGISTRY_SCHEMA_VERSION),
                "name": self.name,
                "family": self.family,
            }
            for key, value in expected.items():
                self._connection.execute(
                    "INSERT OR IGNORE INTO registry_meta(key, value) VALUES (?, ?)",
                    (key, value),
                )
                observed = self._connection.execute(
                    "SELECT value FROM registry_meta WHERE key = ?", (key,)
                ).fetchone()
                if observed is None or observed["value"] != value:
                    raise DataContractError(
                        f"registry metadata mismatch for {key}: expected {value!r}"
                    )

    def close(self) -> None:
        with self._lock:
            if self._finalizer.alive:
                self._finalizer()

    def __enter__(self) -> ExperimentRegistry:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _trial_id(
        self,
        *,
        parameters: Mapping[str, object],
        method: str,
        method_version: int,
        data_fingerprint: str | None,
        code_fingerprint: str | None,
    ) -> str:
        identity = fingerprint(
            {
                "family": self.family,
                "experiment": self.name,
                "parameters": parameters,
                "method": method,
                "method_version": method_version,
                "data_fingerprint": data_fingerprint,
                "code_fingerprint": code_fingerprint,
            },
            namespace="experiment-trial",
        )
        return f"trial_{identity.rsplit(':', 1)[1][:32]}"

    def record(
        self,
        *,
        parameters: Mapping[str, object],
        metric: float | None = None,
        metric_name: str = "objective",
        status: AttemptStatus | str = "completed",
        method: str = "user.evaluation",
        method_version: int = 1,
        data_fingerprint: str | None = None,
        code_fingerprint: str | None = None,
        result_fingerprint: str | None = None,
        error_category: str | None = None,
        supersedes_attempt_id: str | None = None,
        supersedes_reason: str | None = None,
        metadata: Mapping[str, object] | None = None,
        created_at: datetime | None = None,
        attempt_id: str | None = None,
    ) -> AttemptRecord:
        """Append one terminal attempt without mutating prior history."""

        try:
            resolved_status = AttemptStatus(status)
        except ValueError as error:
            raise MethodContractError("status must be completed, failed, or cancelled") from error
        if not method or method.strip() != method:
            raise MethodContractError("method must be a non-empty trimmed string")
        if method_version < 1:
            raise MethodContractError("method_version must be positive")
        if metric is not None and not math.isfinite(float(metric)):
            raise DataContractError("metric must be finite when provided")
        if metric is not None and (not metric_name or metric_name.strip() != metric_name):
            raise MethodContractError("metric_name must be a non-empty trimmed string")
        if resolved_status is AttemptStatus.COMPLETED and error_category is not None:
            raise MethodContractError("completed attempts cannot have an error_category")
        if resolved_status is AttemptStatus.FAILED and not error_category:
            raise MethodContractError("failed attempts require an error_category")
        if resolved_status is not AttemptStatus.COMPLETED and metric is not None:
            raise MethodContractError("failed or cancelled attempts cannot record a metric")
        if (supersedes_attempt_id is None) != (supersedes_reason is None):
            raise MethodContractError(
                "supersedes_attempt_id and supersedes_reason must be provided together"
            )
        if supersedes_reason is not None and not supersedes_reason.strip():
            raise MethodContractError("supersedes_reason must be non-empty")

        parameters_json = canonical_json(parameters)
        metadata_json = canonical_json(metadata or {})
        normalized_parameters = cast(Mapping[str, object], json.loads(parameters_json))
        trial_id = self._trial_id(
            parameters=normalized_parameters,
            method=method,
            method_version=method_version,
            data_fingerprint=data_fingerprint,
            code_fingerprint=code_fingerprint,
        )
        resolved_attempt_id = attempt_id or f"attempt_{uuid.uuid4().hex}"
        if not resolved_attempt_id or resolved_attempt_id.strip() != resolved_attempt_id:
            raise MethodContractError("attempt_id must be a non-empty trimmed string")
        created_text = _utc_text(created_at or datetime.now(UTC))

        with self._lock, self._connection:
            if supersedes_attempt_id is not None:
                previous = self._connection.execute(
                    "SELECT trial_id FROM attempts WHERE attempt_id = ?", (supersedes_attempt_id,)
                ).fetchone()
                if previous is None:
                    raise DataContractError("superseded attempt does not exist")
                if previous["trial_id"] != trial_id:
                    raise DataContractError(
                        "a correction must supersede an attempt for the same trial"
                    )
            try:
                cursor = self._connection.execute(
                    """
                    INSERT INTO attempts(
                        attempt_id, trial_id, family, experiment, created_at, status,
                        parameters_json, metric_name, metric_value, method, method_version,
                        data_fingerprint, code_fingerprint, result_fingerprint, error_category,
                        supersedes_attempt_id, supersedes_reason, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        resolved_attempt_id,
                        trial_id,
                        self.family,
                        self.name,
                        created_text,
                        resolved_status.value,
                        parameters_json,
                        metric_name if metric is not None else None,
                        float(metric) if metric is not None else None,
                        method,
                        method_version,
                        data_fingerprint,
                        code_fingerprint,
                        result_fingerprint,
                        error_category,
                        supersedes_attempt_id,
                        supersedes_reason,
                        metadata_json,
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise DataContractError(
                    f"attempt_id already exists: {resolved_attempt_id}"
                ) from error
            row = self._connection.execute(
                f"SELECT {_ATTEMPT_COLUMNS} FROM attempts WHERE sequence = ?",
                (cursor.lastrowid,),
            ).fetchone()
        if row is None:  # pragma: no cover - SQLite insert/read invariant
            raise RuntimeError("inserted attempt could not be read")
        return self._attempt_from_row(row)

    @staticmethod
    def _attempt_from_row(row: sqlite3.Row) -> AttemptRecord:
        return AttemptRecord(
            sequence=int(row["sequence"]),
            attempt_id=str(row["attempt_id"]),
            trial_id=str(row["trial_id"]),
            family=str(row["family"]),
            experiment=str(row["experiment"]),
            created_at=_utc_datetime(str(row["created_at"])),
            status=AttemptStatus(str(row["status"])),
            parameters=_mapping_from_json(str(row["parameters_json"])),
            metric_name=cast(str | None, row["metric_name"]),
            metric_value=(float(row["metric_value"]) if row["metric_value"] is not None else None),
            method=str(row["method"]),
            method_version=int(row["method_version"]),
            data_fingerprint=cast(str | None, row["data_fingerprint"]),
            code_fingerprint=cast(str | None, row["code_fingerprint"]),
            result_fingerprint=cast(str | None, row["result_fingerprint"]),
            error_category=cast(str | None, row["error_category"]),
            supersedes_attempt_id=cast(str | None, row["supersedes_attempt_id"]),
            supersedes_reason=cast(str | None, row["supersedes_reason"]),
            metadata=_mapping_from_json(str(row["metadata_json"])),
        )

    def attempts(self) -> tuple[AttemptRecord, ...]:
        with self._lock:
            rows = self._connection.execute(
                f"SELECT {_ATTEMPT_COLUMNS} FROM attempts ORDER BY sequence"
            ).fetchall()
        return tuple(self._attempt_from_row(row) for row in rows)

    def record_selection(
        self,
        *,
        eligible_trial_ids: Sequence[str],
        selected_trial_ids: Sequence[str],
        metric: str,
        direction: str = "maximize",
        tie_breaking: str = "trial_id",
        used_holdout: bool = False,
        actor: str | None = None,
        exclusion_reasons: Mapping[str, object] | None = None,
        created_at: datetime | None = None,
        selection_id: str | None = None,
    ) -> SelectionRecord:
        """Append a selection decision while preserving its full eligible candidate set."""

        eligible = tuple(eligible_trial_ids)
        selected = tuple(selected_trial_ids)
        if not eligible or len(set(eligible)) != len(eligible):
            raise MethodContractError("eligible_trial_ids must be non-empty and unique")
        if not selected or len(set(selected)) != len(selected):
            raise MethodContractError("selected_trial_ids must be non-empty and unique")
        if not set(selected).issubset(eligible):
            raise MethodContractError("selected trials must belong to the eligible set")
        if direction not in {"maximize", "minimize"}:
            raise MethodContractError("direction must be 'maximize' or 'minimize'")
        if not metric or metric.strip() != metric:
            raise MethodContractError("selection metric must be a non-empty trimmed string")
        if not tie_breaking or tie_breaking.strip() != tie_breaking:
            raise MethodContractError("tie_breaking must be a non-empty trimmed string")
        if actor is not None and not actor.strip():
            raise MethodContractError("actor must be non-empty when provided")
        reasons_json = canonical_json(exclusion_reasons or {})
        reasons = json.loads(reasons_json)
        if not isinstance(reasons, dict):  # pragma: no cover - mapping input invariant
            raise RuntimeError("selection exclusions did not encode as a mapping")
        unknown_reason_ids = set(reasons).difference(eligible)
        if unknown_reason_ids:
            raise MethodContractError("exclusion reasons contain a trial outside the eligible set")
        if set(reasons).intersection(selected):
            raise MethodContractError("selected trials cannot have exclusion reasons")

        with self._lock, self._connection:
            for trial_id in eligible:
                exists = self._connection.execute(
                    "SELECT 1 FROM attempts WHERE trial_id = ? LIMIT 1", (trial_id,)
                ).fetchone()
                if exists is None:
                    raise DataContractError(f"eligible trial is not recorded: {trial_id}")
            resolved_id = selection_id or f"selection_{uuid.uuid4().hex}"
            try:
                cursor = self._connection.execute(
                    """
                    INSERT INTO selections(
                        selection_id, created_at, eligible_trial_ids_json,
                        selected_trial_ids_json, metric, direction, tie_breaking,
                        used_holdout, actor, exclusion_reasons_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        resolved_id,
                        _utc_text(created_at or datetime.now(UTC)),
                        canonical_json(eligible),
                        canonical_json(selected),
                        metric,
                        direction,
                        tie_breaking,
                        int(used_holdout),
                        actor,
                        reasons_json,
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise DataContractError(f"selection_id already exists: {resolved_id}") from error
            row = self._connection.execute(
                "SELECT * FROM selections WHERE sequence = ?", (cursor.lastrowid,)
            ).fetchone()
        if row is None:  # pragma: no cover - SQLite insert/read invariant
            raise RuntimeError("inserted selection could not be read")
        return self._selection_from_row(row)

    @staticmethod
    def _selection_from_row(row: sqlite3.Row) -> SelectionRecord:
        eligible = json.loads(str(row["eligible_trial_ids_json"]))
        selected = json.loads(str(row["selected_trial_ids_json"]))
        if not isinstance(eligible, list) or not isinstance(selected, list):
            raise RuntimeError("registry selection payload is corrupt")
        return SelectionRecord(
            sequence=int(row["sequence"]),
            selection_id=str(row["selection_id"]),
            created_at=_utc_datetime(str(row["created_at"])),
            eligible_trial_ids=tuple(str(item) for item in eligible),
            selected_trial_ids=tuple(str(item) for item in selected),
            metric=str(row["metric"]),
            direction=str(row["direction"]),
            tie_breaking=str(row["tie_breaking"]),
            used_holdout=bool(row["used_holdout"]),
            actor=cast(str | None, row["actor"]),
            exclusion_reasons=_mapping_from_json(str(row["exclusion_reasons_json"])),
        )

    def selections(self) -> tuple[SelectionRecord, ...]:
        with self._lock:
            rows = self._connection.execute("SELECT * FROM selections ORDER BY sequence").fetchall()
        return tuple(self._selection_from_row(row) for row in rows)

    def to_result(self) -> AnalysisResult:
        """Return a structured, immutable snapshot suitable for audit and reporting."""

        attempts = self.attempts()
        selections = self.selections()
        completed = sum(item.status is AttemptStatus.COMPLETED for item in attempts)
        failed = sum(item.status is AttemptStatus.FAILED for item in attempts)
        cancelled = sum(item.status is AttemptStatus.CANCELLED for item in attempts)
        trial_count = len({item.trial_id for item in attempts})
        incomplete_identity = sum(
            item.data_fingerprint is None or item.code_fingerprint is None for item in attempts
        )
        findings: list[Finding] = []
        if failed:
            findings.append(
                Finding(
                    code="EXPERIMENT_FAILED_ATTEMPTS",
                    title="Experiment history includes failed attempts",
                    message=(
                        "Failed attempts remain visible and must be considered during selection."
                    ),
                    state=FindingState.WARN,
                    severity=Severity.MEDIUM,
                    category="research_process",
                    evidence={"failed_attempts": failed, "attempts": len(attempts)},
                )
            )
        if incomplete_identity:
            findings.append(
                Finding(
                    code="EXPERIMENT_IDENTITY_INCOMPLETE",
                    title="Experiment identity is incomplete",
                    message="One or more attempts lack a data or code fingerprint.",
                    state=FindingState.UNKNOWN,
                    severity=Severity.MEDIUM,
                    category="reproducibility",
                    evidence={"incomplete_attempts": incomplete_identity},
                )
            )
        if attempts and not selections:
            findings.append(
                Finding(
                    code="EXPERIMENT_SELECTION_MISSING",
                    title="Selection lineage is not recorded",
                    message="Trials exist, but no explicit selection decision has been registered.",
                    state=FindingState.UNKNOWN,
                    severity=Severity.LOW,
                    category="research_process",
                    evidence={"trial_count": trial_count},
                )
            )
        attempt_rows = [item.to_dict() for item in attempts]
        selection_rows = [item.to_dict() for item in selections]
        snapshot_fingerprint = fingerprint(
            {"attempts": attempt_rows, "selections": selection_rows},
            namespace="experiment-registry-snapshot",
        )
        attempt_table = _freeze_json(json.loads(canonical_json(attempt_rows)))
        selection_table = _freeze_json(json.loads(canonical_json(selection_rows)))
        return AnalysisResult(
            metadata=ResultMetadata(
                method="experiment.registry_snapshot",
                method_version=1,
                parameters={
                    "name": self.name,
                    "family": self.family,
                    "storage": "memory" if self._path is None else "sqlite",
                    "schema_version": REGISTRY_SCHEMA_VERSION,
                    "canonicalization_version": CANONICALIZATION_VERSION,
                },
                input_fingerprint=snapshot_fingerprint,
            ),
            metrics={
                "attempt_count": len(attempts),
                "trial_count": trial_count,
                "completed_attempts": completed,
                "failed_attempts": failed,
                "cancelled_attempts": cancelled,
                "selection_count": len(selections),
                "identity_incomplete_attempts": incomplete_identity,
            },
            findings=tuple(findings),
            tables={"attempts": attempt_table, "selections": selection_table},
            warnings=(
                "A local registry cannot prove that unrecorded external trials do not exist.",
            ),
        )


__all__ = [
    "CANONICALIZATION_VERSION",
    "REGISTRY_SCHEMA_VERSION",
    "AttemptRecord",
    "AttemptStatus",
    "ExperimentRegistry",
    "SelectionRecord",
    "canonical_json",
    "fingerprint",
]
