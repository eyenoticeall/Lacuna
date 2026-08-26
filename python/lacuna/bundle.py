"""Deterministic, non-executable reproducibility bundles and verification."""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import os
import platform
import re
import stat
import tempfile
import zipfile
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as distribution_version
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import TYPE_CHECKING, cast
from urllib.parse import urlsplit, urlunsplit

from lacuna._version import __version__
from lacuna.config import get_config
from lacuna.exceptions import DataContractError, ReportError
from lacuna.experiment import canonical_json
from lacuna.native import native_status
from lacuna.types import AnalysisResult

if TYPE_CHECKING:
    from lacuna.report import AuditReport

BUNDLE_FORMAT = "lacuna.reproducibility-bundle"
BUNDLE_VERSION = 1

_MANIFEST_PATH = "manifest.json"
_FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
_MAX_ARCHIVE_SIZE = 64 * 1024 * 1024
_MAX_MEMBER_SIZE = 16 * 1024 * 1024
_MAX_TOTAL_SIZE = 64 * 1024 * 1024
_MAX_MEMBERS = 256
_EVIDENCE_NAME = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
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
_ROLES = {
    "canonical_report",
    "configuration",
    "environment",
    "evidence",
    "invocation",
    "provenance",
    "redaction_log",
    "rendered_report",
}


def _is_sensitive_key(key: str) -> bool:
    normalized = key.casefold().replace("-", "_")
    return normalized in _SENSITIVE_KEYS or any(
        normalized.endswith(f"_{suffix}") for suffix in _SENSITIVE_KEYS
    )


def _is_absolute_path(value: str) -> bool:
    return PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute()


def _redacted_url(value: str) -> tuple[str, bool]:
    parsed = urlsplit(value)
    if parsed.scheme.casefold() not in {"ftp", "ftps", "gs", "http", "https", "s3"}:
        return value, False
    unsafe = bool(parsed.query or parsed.fragment or parsed.username or parsed.password)
    if not unsafe:
        return value, False
    netloc = parsed.netloc.rsplit("@", maxsplit=1)[-1]
    return urlunsplit((parsed.scheme, netloc, parsed.path, "", "")), True


def _safe_path_label(value: str) -> str:
    windows = PureWindowsPath(value)
    name = windows.name if windows.is_absolute() else PurePosixPath(value).name
    return f"<absolute-path>/{name}" if name else "<absolute-path>"


def _sanitize_supplemental(
    value: object,
    *,
    artifact: str,
    path: str,
    redactions: list[dict[str, str]],
) -> object:
    if isinstance(value, Mapping):
        normalized: dict[str, object] = {}
        if any(not isinstance(key, str) for key in value):
            raise DataContractError(f"{path} contains a non-string mapping key")
        for key in sorted(value):
            item = value[key]
            if not isinstance(key, str):
                raise RuntimeError("validated bundle mapping key changed type")
            child_path = f"{path}.{key}"
            if _is_sensitive_key(key):
                redacted_key = f"{key}_redacted"
                if redacted_key in value or redacted_key in normalized:
                    raise DataContractError(
                        f"{path} cannot redact {key!r} because {redacted_key!r} already exists"
                    )
                normalized[redacted_key] = "<redacted>"
                redactions.append(
                    {"artifact": artifact, "path": child_path, "reason": "credential_key"}
                )
            else:
                normalized[key] = _sanitize_supplemental(
                    item,
                    artifact=artifact,
                    path=child_path,
                    redactions=redactions,
                )
        return normalized
    if isinstance(value, list | tuple):
        return [
            _sanitize_supplemental(
                item,
                artifact=artifact,
                path=f"{path}[{index}]",
                redactions=redactions,
            )
            for index, item in enumerate(value)
        ]
    if isinstance(value, str):
        redacted, changed = _redacted_url(value)
        if changed:
            redactions.append(
                {"artifact": artifact, "path": path, "reason": "url_credentials_or_query"}
            )
            return redacted
        if _is_absolute_path(value):
            redactions.append({"artifact": artifact, "path": path, "reason": "absolute_path"})
            return _safe_path_label(value)
    return value


def _assert_canonical_evidence_safe(value: object, *, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if _is_sensitive_key(str(key)):
                raise ReportError(
                    f"canonical evidence at {path}.{key} looks credential-bearing; "
                    "remove or redact it before bundling"
                )
            _assert_canonical_evidence_safe(item, path=f"{path}.{key}")
        return
    if isinstance(value, list | tuple):
        for index, item in enumerate(value):
            _assert_canonical_evidence_safe(item, path=f"{path}[{index}]")
        return
    if isinstance(value, str):
        _, unsafe_url = _redacted_url(value)
        if unsafe_url:
            raise ReportError(
                f"canonical evidence at {path} contains URL credentials, a query, or a fragment; "
                "remove or redact it before bundling"
            )
        if _is_absolute_path(value):
            raise ReportError(
                f"canonical evidence at {path} contains an absolute path; "
                "replace it with a portable identity before bundling"
            )


def _canonical_bytes(value: object) -> bytes:
    return (canonical_json(value) + "\n").encode("utf-8")


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _validate_member_path(path: str) -> None:
    if not path or "\\" in path or "\x00" in path:
        raise ReportError(f"bundle contains an unsafe member path: {path!r}")
    candidate = PurePosixPath(path)
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        raise ReportError(f"bundle contains an unsafe member path: {path!r}")
    if PureWindowsPath(path).drive:
        raise ReportError(f"bundle contains an unsafe member path: {path!r}")
    if candidate.as_posix() != path:
        raise ReportError(f"bundle member path is not canonical: {path!r}")


@dataclass(frozen=True, slots=True)
class BundleArtifact:
    """One checksummed member declared by a bundle manifest."""

    path: str
    role: str
    media_type: str
    sha256: str
    size: int

    def __post_init__(self) -> None:
        if not isinstance(self.path, str):
            raise TypeError("bundle artifact path must be a string")
        _validate_member_path(self.path)
        if self.path == _MANIFEST_PATH:
            raise ReportError("the manifest cannot declare itself as an artifact")
        if not isinstance(self.role, str) or self.role not in _ROLES:
            raise ReportError(f"unsupported bundle artifact role: {self.role!r}")
        if (
            not isinstance(self.media_type, str)
            or not self.media_type
            or self.media_type.strip() != self.media_type
        ):
            raise ReportError("bundle artifact media_type must be a non-empty trimmed string")
        if not isinstance(self.sha256, str) or _SHA256.fullmatch(self.sha256) is None:
            raise ReportError("bundle artifact sha256 must be 64 lowercase hexadecimal characters")
        if isinstance(self.size, bool) or not isinstance(self.size, int) or self.size < 0:
            raise ReportError("bundle artifact size must be a non-negative integer")

    def to_dict(self) -> dict[str, object]:
        return {
            "media_type": self.media_type,
            "path": self.path,
            "role": self.role,
            "sha256": self.sha256,
            "size": self.size,
        }


@dataclass(frozen=True, slots=True)
class BundleManifest:
    """Parsed version-1 manifest for a Lacuna reproducibility bundle."""

    producer_version: str
    report_schema_version: str
    report_method: str
    report_method_version: int
    report_input_fingerprint: str | None
    artifact_set_sha256: str
    artifacts: tuple[BundleArtifact, ...]
    format: str = BUNDLE_FORMAT
    bundle_version: int = BUNDLE_VERSION
    reproducibility_level: str = "identifiable"

    def __post_init__(self) -> None:
        if self.format != BUNDLE_FORMAT:
            raise ReportError(f"unsupported bundle format: {self.format!r}")
        if self.bundle_version != BUNDLE_VERSION:
            raise ReportError(f"unsupported bundle version: {self.bundle_version!r}")
        if not isinstance(self.producer_version, str) or not self.producer_version:
            raise ReportError("bundle producer version must not be empty")
        if (
            not isinstance(self.report_schema_version, str)
            or not self.report_schema_version
            or not isinstance(self.report_method, str)
            or not self.report_method
        ):
            raise ReportError("bundle report identity is incomplete")
        if (
            isinstance(self.report_method_version, bool)
            or not isinstance(self.report_method_version, int)
            or self.report_method_version < 1
        ):
            raise ReportError("bundle report method version must be positive")
        if self.report_input_fingerprint is not None and (
            not isinstance(self.report_input_fingerprint, str) or not self.report_input_fingerprint
        ):
            raise ReportError("bundle report input fingerprint must be non-empty when supplied")
        if self.reproducibility_level != "identifiable":
            raise ReportError("bundle v1 supports only the verified 'identifiable' level")
        if (
            not isinstance(self.artifact_set_sha256, str)
            or _SHA256.fullmatch(self.artifact_set_sha256) is None
        ):
            raise ReportError("artifact_set_sha256 must be 64 lowercase hexadecimal characters")
        if any(not isinstance(artifact, BundleArtifact) for artifact in self.artifacts):
            raise TypeError("bundle manifest artifacts must contain BundleArtifact values")
        object.__setattr__(self, "artifacts", tuple(self.artifacts))
        paths = tuple(artifact.path for artifact in self.artifacts)
        if not paths or paths != tuple(sorted(paths)) or len(paths) != len(set(paths)):
            raise ReportError("bundle artifacts must be non-empty, uniquely path-sorted entries")
        canonical = [
            artifact
            for artifact in self.artifacts
            if artifact.path == "report/audit.json" and artifact.role == "canonical_report"
        ]
        if len(canonical) != 1:
            raise ReportError("bundle must contain one canonical report/audit.json artifact")

    def to_dict(self) -> dict[str, object]:
        return {
            "artifact_set_sha256": self.artifact_set_sha256,
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "bundle_version": self.bundle_version,
            "format": self.format,
            "producer": {"name": "lacuna", "version": self.producer_version},
            "report": {
                "input_fingerprint": self.report_input_fingerprint,
                "method": self.report_method,
                "method_version": self.report_method_version,
                "path": "report/audit.json",
                "schema_version": self.report_schema_version,
            },
            "reproducibility": {
                "level": self.reproducibility_level,
                "scope": "artifact identity and archive integrity",
                "verified": True,
            },
            "security": {
                "absolute_paths": "redacted_or_rejected",
                "credentials": "redacted_or_rejected",
                "executable_code": False,
                "plugins_activated": False,
                "source_data": "not_included_automatically",
            },
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> BundleManifest:
        """Parse a strict standalone bundle-v1 manifest without reading archive members."""

        if cls is not BundleManifest:
            raise TypeError("BundleManifest.from_dict does not construct subclasses")
        if not isinstance(value, Mapping):
            raise TypeError("bundle manifest must be a mapping")
        return _parse_manifest(value)

    @classmethod
    def from_json(cls, value: str) -> BundleManifest:
        """Parse finite bundle-v1 manifest JSON while rejecting duplicate keys."""

        if cls is not BundleManifest:
            raise TypeError("BundleManifest.from_json does not construct subclasses")
        if not isinstance(value, str):
            raise TypeError("bundle manifest JSON must be a string")

        def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, item in pairs:
                if key in result:
                    raise ReportError(f"bundle manifest JSON contains duplicate key {key!r}")
                result[key] = item
            return result

        def reject_constant(constant: str) -> object:
            raise ReportError(f"bundle manifest JSON contains non-finite value {constant!r}")

        try:
            parsed = json.loads(
                value,
                object_pairs_hook=reject_duplicates,
                parse_constant=reject_constant,
            )
        except json.JSONDecodeError as error:
            raise ReportError(f"invalid bundle manifest JSON: {error.msg}") from error
        if not isinstance(parsed, Mapping):
            raise ReportError("bundle manifest JSON must contain an object at the top level")
        return _parse_manifest(parsed)


@dataclass(frozen=True, slots=True)
class BundleVerification:
    """Successful structural and digest verification of a local bundle."""

    path: Path
    manifest: BundleManifest
    archive_sha256: str
    total_size: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", Path(self.path))
        if not isinstance(self.manifest, BundleManifest):
            raise TypeError("bundle verification manifest must be a BundleManifest")
        if (
            not isinstance(self.archive_sha256, str)
            or _SHA256.fullmatch(self.archive_sha256) is None
        ):
            raise ReportError("archive_sha256 must be 64 lowercase hexadecimal characters")
        if (
            isinstance(self.total_size, bool)
            or not isinstance(self.total_size, int)
            or self.total_size < 0
        ):
            raise ReportError("bundle total size must be non-negative")

    @property
    def artifact_count(self) -> int:
        return len(self.manifest.artifacts)

    def to_dict(self) -> dict[str, object]:
        return {
            "archive_sha256": self.archive_sha256,
            "artifact_count": self.artifact_count,
            "authenticity_verified": False,
            "bundle_version": self.manifest.bundle_version,
            "format": self.manifest.format,
            "integrity_verified": True,
            "path": str(self.path),
            "reproducibility_level": self.manifest.reproducibility_level,
            "total_size": self.total_size,
        }


def _artifact(path: str, role: str, media_type: str, content: bytes) -> BundleArtifact:
    return BundleArtifact(
        path=path,
        role=role,
        media_type=media_type,
        sha256=_digest(content),
        size=len(content),
    )


def _package_version(name: str) -> str | None:
    try:
        return distribution_version(name)
    except PackageNotFoundError:
        return None


def _environment_summary() -> dict[str, object]:
    native = native_status()
    return {
        "native": {"available": native.available, "version": native.version},
        "packages": {
            "lacuna": __version__,
            "numpy": _package_version("numpy"),
            "polars": _package_version("polars"),
        },
        "python": {
            "implementation": platform.python_implementation(),
            "version": platform.python_version(),
        },
        "runtime": {"machine": platform.machine(), "system": platform.system()},
        "schema_version": 1,
    }


def _configuration_summary() -> dict[str, object]:
    configuration = get_config()
    return {
        "cache_dir": configuration.cache_dir,
        "log_level": configuration.log_level,
        "memory_limit": configuration.memory_limit,
        "seed": configuration.seed,
        "threads": configuration.threads,
    }


def _add_json_member(
    members: dict[str, bytes],
    roles: dict[str, tuple[str, str]],
    *,
    path: str,
    role: str,
    value: object,
    redactions: list[dict[str, str]],
) -> None:
    sanitized = _sanitize_supplemental(
        value,
        artifact=path,
        path="$",
        redactions=redactions,
    )
    members[path] = _canonical_bytes(sanitized)
    roles[path] = (role, "application/json")


def _write_zip(members: Mapping[str, bytes]) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, mode="w", compression=zipfile.ZIP_STORED) as archive:
        for name in sorted(members):
            info = zipfile.ZipInfo(name, date_time=_FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o600) << 16
            archive.writestr(info, members[name])
    return stream.getvalue()


def _persist_archive(destination: Path, content: bytes, *, overwrite: bool) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not overwrite:
        try:
            descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as error:
            raise ReportError(f"refusing to overwrite existing bundle: {destination}") from error
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(content)
        except BaseException:
            with suppress(FileNotFoundError):
                destination.unlink()
            raise
        return destination

    descriptor, temporary_name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
        os.replace(temporary, destination)
    finally:
        with suppress(FileNotFoundError):
            temporary.unlink()
    return destination


def create_bundle(
    report: AuditReport,
    path: str | os.PathLike[str],
    *,
    configuration: Mapping[str, object] | None = None,
    evidence: Mapping[str, AnalysisResult] | None = None,
    provenance: Mapping[str, object] | None = None,
    invocation: Mapping[str, object] | None = None,
    overwrite: bool = False,
) -> Path:
    """Create a deterministic version-1 evidence bundle without source data or code."""

    from lacuna.report import AuditReport

    if not isinstance(report, AuditReport):
        raise TypeError("report must be an AuditReport")
    for name, value in (
        ("configuration", configuration),
        ("evidence", evidence),
        ("provenance", provenance),
        ("invocation", invocation),
    ):
        if value is not None and not isinstance(value, Mapping):
            raise TypeError(f"{name} must be a mapping when supplied")

    destination = Path(path)
    if destination.suffix.casefold() != ".lacuna":
        raise ReportError("reproducibility bundle paths must use the .lacuna suffix")

    report_payload = report.result.to_dict()
    _assert_canonical_evidence_safe(report_payload)
    members: dict[str, bytes] = {
        "report/audit.html": report.to_html().encode("utf-8"),
        "report/audit.json": _canonical_bytes(report_payload),
        "report/audit.md": report.to_markdown().encode("utf-8"),
    }
    roles: dict[str, tuple[str, str]] = {
        "report/audit.html": ("rendered_report", "text/html; charset=utf-8"),
        "report/audit.json": ("canonical_report", "application/json"),
        "report/audit.md": ("rendered_report", "text/markdown; charset=utf-8"),
    }
    redactions: list[dict[str, str]] = []
    _add_json_member(
        members,
        roles,
        path="metadata/configuration.json",
        role="configuration",
        value=_configuration_summary() if configuration is None else configuration,
        redactions=redactions,
    )
    _add_json_member(
        members,
        roles,
        path="metadata/environment.json",
        role="environment",
        value=_environment_summary(),
        redactions=redactions,
    )
    if provenance is not None:
        _add_json_member(
            members,
            roles,
            path="metadata/provenance.json",
            role="provenance",
            value=provenance,
            redactions=redactions,
        )
    if invocation is not None:
        _add_json_member(
            members,
            roles,
            path="metadata/invocation.json",
            role="invocation",
            value=invocation,
            redactions=redactions,
        )

    for name, result in sorted((evidence or {}).items()):
        if _EVIDENCE_NAME.fullmatch(name) is None:
            raise ReportError("bundle evidence names must match [a-z][a-z0-9_-]{0,63}")
        if not isinstance(result, AnalysisResult):
            raise TypeError("bundle evidence values must be AnalysisResult instances")
        payload = result.to_dict()
        _assert_canonical_evidence_safe(payload, path=f"$.evidence.{name}")
        member_path = f"evidence/{name}.json"
        members[member_path] = _canonical_bytes(payload)
        roles[member_path] = ("evidence", "application/json")

    if redactions:
        members["metadata/redactions.json"] = _canonical_bytes(
            {"redactions": redactions, "schema_version": 1}
        )
        roles["metadata/redactions.json"] = ("redaction_log", "application/json")

    artifacts = tuple(
        _artifact(member_path, *roles[member_path], members[member_path])
        for member_path in sorted(members)
    )
    artifact_set_sha256 = _digest(_canonical_bytes([item.to_dict() for item in artifacts]))
    manifest = BundleManifest(
        producer_version=__version__,
        report_schema_version=report.result.schema_version,
        report_method=report.result.metadata.method,
        report_method_version=report.result.metadata.method_version,
        report_input_fingerprint=report.result.metadata.input_fingerprint,
        artifact_set_sha256=artifact_set_sha256,
        artifacts=artifacts,
    )
    members[_MANIFEST_PATH] = _canonical_bytes(manifest.to_dict())
    if len(members) > _MAX_MEMBERS:
        raise ReportError(f"bundle exceeds the {_MAX_MEMBERS}-member version-1 safety limit")
    oversized = [name for name, content in members.items() if len(content) > _MAX_MEMBER_SIZE]
    if oversized:
        raise ReportError(
            f"bundle member {sorted(oversized)[0]!r} exceeds the "
            f"{_MAX_MEMBER_SIZE}-byte version-1 safety limit"
        )
    total_size = sum(len(content) for content in members.values())
    if total_size > _MAX_TOTAL_SIZE:
        raise ReportError(
            f"bundle members exceed the {_MAX_TOTAL_SIZE}-byte total version-1 safety limit"
        )
    archive = _write_zip(members)
    if len(archive) > _MAX_ARCHIVE_SIZE:
        raise ReportError(
            f"bundle archive exceeds the {_MAX_ARCHIVE_SIZE}-byte version-1 safety limit"
        )
    return _persist_archive(destination, archive, overwrite=overwrite)


def _json_object(content: bytes, *, path: str) -> dict[str, object]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ReportError(f"{path} contains duplicate JSON key {key!r}")
            result[key] = value
        return result

    def reject_constant(value: str) -> object:
        raise ReportError(f"{path} contains non-finite JSON value {value}")

    try:
        decoded = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReportError(f"{path} is not valid UTF-8 JSON") from error
    if not isinstance(decoded, dict):
        raise ReportError(f"{path} must contain a JSON object")
    try:
        canonical = _canonical_bytes(decoded)
    except DataContractError as error:
        raise ReportError(f"{path} is not canonical Lacuna JSON: {error}") from error
    if content != canonical:
        raise ReportError(f"{path} is not in canonical Lacuna JSON form")
    return decoded


def _require_exact_keys(value: Mapping[str, object], expected: set[str], *, path: str) -> None:
    observed = set(value)
    if observed != expected:
        raise ReportError(
            f"{path} fields differ from bundle v1: "
            f"missing={sorted(expected - observed)}, extra={sorted(observed - expected)}"
        )


def _mapping(value: object, *, path: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ReportError(f"{path} must be an object")
    return value


def _text(value: object, *, path: str, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not value:
        raise ReportError(f"{path} must be a non-empty string")
    return value


def _integer(value: object, *, path: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ReportError(f"{path} must be an integer greater than or equal to {minimum}")
    return value


def _parse_artifact(value: object, *, index: int) -> BundleArtifact:
    item = _mapping(value, path=f"$.artifacts[{index}]")
    _require_exact_keys(
        item,
        {"media_type", "path", "role", "sha256", "size"},
        path=f"$.artifacts[{index}]",
    )
    return BundleArtifact(
        path=cast(str, _text(item["path"], path=f"$.artifacts[{index}].path")),
        role=cast(str, _text(item["role"], path=f"$.artifacts[{index}].role")),
        media_type=cast(str, _text(item["media_type"], path=f"$.artifacts[{index}].media_type")),
        sha256=cast(str, _text(item["sha256"], path=f"$.artifacts[{index}].sha256")),
        size=_integer(item["size"], path=f"$.artifacts[{index}].size"),
    )


def _parse_manifest(value: Mapping[str, object]) -> BundleManifest:
    _require_exact_keys(
        value,
        {
            "artifact_set_sha256",
            "artifacts",
            "bundle_version",
            "format",
            "producer",
            "report",
            "reproducibility",
            "security",
        },
        path="$",
    )
    producer = _mapping(value["producer"], path="$.producer")
    _require_exact_keys(producer, {"name", "version"}, path="$.producer")
    if producer["name"] != "lacuna":
        raise ReportError("$.producer.name must be 'lacuna'")
    report = _mapping(value["report"], path="$.report")
    _require_exact_keys(
        report,
        {"input_fingerprint", "method", "method_version", "path", "schema_version"},
        path="$.report",
    )
    if report["path"] != "report/audit.json":
        raise ReportError("$.report.path must be 'report/audit.json'")
    reproducibility = _mapping(value["reproducibility"], path="$.reproducibility")
    _require_exact_keys(reproducibility, {"level", "scope", "verified"}, path="$.reproducibility")
    if reproducibility != {
        "level": "identifiable",
        "scope": "artifact identity and archive integrity",
        "verified": True,
    }:
        raise ReportError("$.reproducibility contains an unsupported claim")
    security = _mapping(value["security"], path="$.security")
    expected_security = {
        "absolute_paths": "redacted_or_rejected",
        "credentials": "redacted_or_rejected",
        "executable_code": False,
        "plugins_activated": False,
        "source_data": "not_included_automatically",
    }
    if security != expected_security:
        raise ReportError("$.security differs from the bundle v1 trust contract")
    raw_artifacts = value["artifacts"]
    if not isinstance(raw_artifacts, list):
        raise ReportError("$.artifacts must be an array")
    artifacts = tuple(
        _parse_artifact(artifact, index=index) for index, artifact in enumerate(raw_artifacts)
    )
    return BundleManifest(
        producer_version=cast(str, _text(producer["version"], path="$.producer.version")),
        report_schema_version=cast(
            str, _text(report["schema_version"], path="$.report.schema_version")
        ),
        report_method=cast(str, _text(report["method"], path="$.report.method")),
        report_method_version=_integer(
            report["method_version"], path="$.report.method_version", minimum=1
        ),
        report_input_fingerprint=_text(
            report["input_fingerprint"], path="$.report.input_fingerprint", nullable=True
        ),
        artifact_set_sha256=cast(
            str, _text(value["artifact_set_sha256"], path="$.artifact_set_sha256")
        ),
        artifacts=artifacts,
        format=cast(str, _text(value["format"], path="$.format")),
        bundle_version=_integer(value["bundle_version"], path="$.bundle_version", minimum=1),
        reproducibility_level=cast(
            str, _text(reproducibility["level"], path="$.reproducibility.level")
        ),
    )


def _validate_zip_info(info: zipfile.ZipInfo) -> None:
    _validate_member_path(info.filename)
    if info.is_dir() or info.compress_type != zipfile.ZIP_STORED:
        raise ReportError(f"bundle member {info.filename!r} is not a stored regular file")
    if info.flag_bits & 0x1:
        raise ReportError(f"bundle member {info.filename!r} is encrypted")
    mode = (info.external_attr >> 16) & 0xFFFF
    if info.create_system != 3 or not stat.S_ISREG(mode) or mode & 0o111:
        raise ReportError(
            f"bundle member {info.filename!r} has unsafe file type or executable permissions"
        )
    if info.file_size > _MAX_MEMBER_SIZE:
        raise ReportError(
            f"bundle member {info.filename!r} exceeds the {_MAX_MEMBER_SIZE}-byte safety limit"
        )
    if info.compress_size != info.file_size:
        raise ReportError(f"bundle member {info.filename!r} has inconsistent stored size")


def verify_bundle(path: str | os.PathLike[str]) -> BundleVerification:
    """Verify bundle structure and SHA-256 integrity without extracting or executing content."""

    source = Path(path)
    try:
        with source.open("rb") as input_file:
            archive_size = os.fstat(input_file.fileno()).st_size
            if archive_size > _MAX_ARCHIVE_SIZE:
                raise ReportError(
                    f"bundle archive exceeds the {_MAX_ARCHIVE_SIZE}-byte version-1 safety limit"
                )
            archive_bytes = input_file.read(_MAX_ARCHIVE_SIZE + 1)
    except OSError as error:
        raise ReportError(f"cannot read bundle: {source}") from error
    if len(archive_bytes) != archive_size or len(archive_bytes) > _MAX_ARCHIVE_SIZE:
        raise ReportError(
            f"bundle archive exceeds the {_MAX_ARCHIVE_SIZE}-byte version-1 safety limit"
        )
    try:
        archive = zipfile.ZipFile(io.BytesIO(archive_bytes), mode="r")
    except (OSError, zipfile.BadZipFile) as error:
        raise ReportError(f"bundle is not a valid ZIP archive: {source}") from error

    with archive:
        if archive.comment:
            raise ReportError("bundle archive comments are not permitted")
        infos = archive.infolist()
        if not infos or len(infos) > _MAX_MEMBERS:
            raise ReportError(f"bundle must contain between 1 and {_MAX_MEMBERS} members")
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise ReportError("bundle contains duplicate member names")
        total_size = 0
        for info in infos:
            _validate_zip_info(info)
            total_size += info.file_size
            if total_size > _MAX_TOTAL_SIZE:
                raise ReportError(
                    f"bundle members exceed the {_MAX_TOTAL_SIZE}-byte total safety limit"
                )
        if _MANIFEST_PATH not in names:
            raise ReportError("bundle does not contain manifest.json")

        member_contents = {info.filename: archive.read(info) for info in infos}
        manifest_payload = _json_object(member_contents[_MANIFEST_PATH], path=_MANIFEST_PATH)
        manifest = _parse_manifest(manifest_payload)
        expected_names = {_MANIFEST_PATH, *(artifact.path for artifact in manifest.artifacts)}
        if set(names) != expected_names:
            raise ReportError(
                "bundle members differ from the manifest: "
                f"missing={sorted(expected_names - set(names))}, "
                f"extra={sorted(set(names) - expected_names)}"
            )

        computed_set_digest = _digest(
            _canonical_bytes([artifact.to_dict() for artifact in manifest.artifacts])
        )
        if not hmac.compare_digest(computed_set_digest, manifest.artifact_set_sha256):
            raise ReportError("bundle artifact-set digest does not match the manifest")

        report_payload: dict[str, object] | None = None
        for artifact in manifest.artifacts:
            content = member_contents[artifact.path]
            if len(content) != artifact.size:
                raise ReportError(f"bundle artifact size mismatch: {artifact.path}")
            if not hmac.compare_digest(_digest(content), artifact.sha256):
                raise ReportError(f"bundle artifact SHA-256 mismatch: {artifact.path}")
            if artifact.media_type == "application/json":
                payload = _json_object(content, path=artifact.path)
                if artifact.path == "report/audit.json":
                    report_payload = payload

        if report_payload is None:
            raise ReportError("bundle canonical report could not be read")
        metadata = _mapping(report_payload.get("metadata"), path="report/audit.json.metadata")
        if (
            report_payload.get("schema_version") != manifest.report_schema_version
            or metadata.get("method") != manifest.report_method
            or metadata.get("method_version") != manifest.report_method_version
            or metadata.get("input_fingerprint") != manifest.report_input_fingerprint
        ):
            raise ReportError("canonical report identity does not match the manifest")
        if archive_bytes != _write_zip(member_contents):
            raise ReportError("bundle ZIP encoding is not in canonical version-1 form")

    return BundleVerification(
        path=source,
        manifest=manifest,
        archive_sha256=_digest(archive_bytes),
        total_size=total_size,
    )


__all__ = [
    "BUNDLE_FORMAT",
    "BUNDLE_VERSION",
    "BundleArtifact",
    "BundleManifest",
    "BundleVerification",
    "create_bundle",
    "verify_bundle",
]
