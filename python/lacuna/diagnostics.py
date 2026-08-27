"""Actionable, non-invasive installation and runtime diagnostics."""

from __future__ import annotations

import json
import math
import platform
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from importlib import import_module
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as distribution_version
from types import MappingProxyType
from typing import cast

import numpy as np
import polars as pl

from lacuna._version import __version__
from lacuna.config import Config, get_config
from lacuna.exceptions import ConfigurationError
from lacuna.native import NativeStatus, native_status
from lacuna.schemas import (
    audit_result_v1_text,
    bundle_manifest_v1_text,
    persisted_artifact_compatibility_v1_text,
    standard_audit_profile_v1_text,
)
from lacuna.types import JsonValue

DIAGNOSTIC_VERSION = 1
MINIMUM_PYTHON = (3, 11)
TESTED_PYTHON = ((3, 11), (3, 12), (3, 13), (3, 14))

_CORE_DISTRIBUTION = "lacuna-quant"
_CONFLICTING_DISTRIBUTION = "lacuna"

_PACKAGE_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:rc[0-9]+)?\Z")
_SUPPORTED_WHEELS = {
    ("Darwin", "arm64"),
    ("Linux", "aarch64"),
    ("Linux", "x86_64"),
    ("Windows", "amd64"),
    ("Windows", "x86_64"),
}


class DiagnosticState(StrEnum):
    """Outcome of one operational diagnostic check."""

    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


def _freeze_value(value: object) -> JsonValue:
    if value is None or isinstance(value, bool | int | str):
        return cast(JsonValue, value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("diagnostic evidence must not contain NaN or infinity")
        return value
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("diagnostic evidence keys must be strings")
        return MappingProxyType({str(key): _freeze_value(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze_value(item) for item in value)
    raise TypeError(f"diagnostic evidence cannot contain {type(value).__name__}")


def _thaw_value(value: JsonValue) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_value(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class DiagnosticCheck:
    """One stable, actionable installation check."""

    code: str
    state: DiagnosticState
    message: str
    evidence: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if re.fullmatch(r"[A-Z][A-Z0-9_]*", self.code) is None:
            raise ValueError(
                "diagnostic check code must use uppercase letters, digits, underscores"
            )
        if not isinstance(self.state, DiagnosticState):
            raise TypeError("diagnostic check state must be a DiagnosticState")
        if not isinstance(self.message, str) or not self.message:
            raise ValueError("diagnostic check message must not be empty")
        frozen = _freeze_value(self.evidence)
        if not isinstance(frozen, Mapping):  # pragma: no cover - mapping input guarantees this
            raise TypeError("diagnostic check evidence must be a mapping")
        object.__setattr__(self, "evidence", frozen)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible check record."""

        return {
            "code": self.code,
            "state": self.state.value,
            "message": self.message,
            "evidence": _thaw_value(cast(JsonValue, self.evidence)),
        }


@dataclass(frozen=True, slots=True)
class InstallationDiagnostics:
    """Versioned snapshot of an installed Lacuna runtime."""

    checks: tuple[DiagnosticCheck, ...]
    distribution_version: str | None
    native: NativeStatus
    configuration: Mapping[str, JsonValue]
    dependencies: Mapping[str, JsonValue]
    runtime: Mapping[str, JsonValue]
    schema_version: str = "1"
    diagnostic_version: int = DIAGNOSTIC_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != "1" or self.diagnostic_version != DIAGNOSTIC_VERSION:
            raise ValueError("unsupported installation diagnostic version")
        if not self.checks or any(not isinstance(item, DiagnosticCheck) for item in self.checks):
            raise TypeError("installation diagnostics require DiagnosticCheck values")
        codes = tuple(item.code for item in self.checks)
        if codes != tuple(sorted(codes)) or len(codes) != len(set(codes)):
            raise ValueError("diagnostic checks must have unique code-sorted identities")
        if not isinstance(self.native, NativeStatus):
            raise TypeError("native must be a NativeStatus")
        for name in ("configuration", "dependencies", "runtime"):
            frozen = _freeze_value(getattr(self, name))
            if not isinstance(frozen, Mapping):  # pragma: no cover - mapping input guarantees this
                raise TypeError(f"{name} must be a mapping")
            object.__setattr__(self, name, frozen)
        object.__setattr__(self, "checks", tuple(self.checks))

    @property
    def status(self) -> DiagnosticState:
        """Return the worst diagnostic state."""

        states = {item.state for item in self.checks}
        if DiagnosticState.FAIL in states:
            return DiagnosticState.FAIL
        if DiagnosticState.WARN in states:
            return DiagnosticState.WARN
        return DiagnosticState.PASS

    @property
    def healthy(self) -> bool:
        """Return whether no release-blocking diagnostic failed."""

        return self.status != DiagnosticState.FAIL

    def to_dict(self) -> dict[str, object]:
        """Return a stable machine-readable payload while preserving legacy doctor fields."""

        return {
            "schema_version": self.schema_version,
            "diagnostic_version": self.diagnostic_version,
            "status": self.status.value,
            "healthy": self.healthy,
            "lacuna_version": __version__,
            "distribution_version": self.distribution_version,
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "native": {
                "available": self.native.available,
                "version": self.native.version,
                "error": None if self.native.available else "native extension unavailable",
            },
            "config": _thaw_value(cast(JsonValue, self.configuration)),
            "dependencies": _thaw_value(cast(JsonValue, self.dependencies)),
            "runtime": _thaw_value(cast(JsonValue, self.runtime)),
            "checks": [item.to_dict() for item in self.checks],
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        """Serialize diagnostics with deterministic key ordering."""

        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)


def _check(
    code: str,
    state: DiagnosticState,
    message: str,
    **evidence: JsonValue,
) -> DiagnosticCheck:
    return DiagnosticCheck(code=code, state=state, message=message, evidence=evidence)


def _configuration_payload(configuration: Config | None) -> dict[str, JsonValue]:
    if configuration is None:
        return {
            "threads": None,
            "seed": None,
            "memory_limit": None,
            "cache_dir": None,
            "log_level": None,
        }
    return {
        "threads": configuration.threads,
        "seed": configuration.seed,
        "memory_limit": configuration.memory_limit,
        "cache_dir": "<configured>" if configuration.cache_dir is not None else None,
        "log_level": configuration.log_level,
    }


def _distribution_metadata_version(name: str) -> str | None:
    try:
        return distribution_version(name)
    except PackageNotFoundError:
        return None


def _native_check() -> tuple[NativeStatus, DiagnosticCheck]:
    try:
        status = native_status()
    except Exception as error:
        status = NativeStatus(False, None, type(error).__name__)
    if not status.available:
        return status, _check(
            "NATIVE_CORE",
            DiagnosticState.FAIL,
            ("The native core is unavailable; install a target-matching lacuna-quant wheel."),
            available=False,
        )
    if status.version != __version__:
        return status, _check(
            "NATIVE_CORE",
            DiagnosticState.FAIL,
            "The native and Python package versions differ; reinstall one matching wheel.",
            available=True,
            native_version=status.version,
            package_version=__version__,
        )
    try:
        native_module = import_module("lacuna._native")
        smoke_value = native_module.checked_mean([1.0, 2.0, 3.0])
    except Exception as error:
        return status, _check(
            "NATIVE_CORE",
            DiagnosticState.FAIL,
            "The native core imported but its smoke operation failed; reinstall the wheel.",
            available=True,
            error_type=type(error).__name__,
            native_version=status.version,
        )
    if smoke_value != 2.0:
        return status, _check(
            "NATIVE_CORE",
            DiagnosticState.FAIL,
            "The native core returned an invalid smoke result; reinstall the wheel.",
            available=True,
            native_version=status.version,
        )
    return status, _check(
        "NATIVE_CORE",
        DiagnosticState.PASS,
        "The native core version matches and its smoke operation passed.",
        available=True,
        native_version=status.version,
    )


def _schema_checks() -> tuple[DiagnosticCheck, ...]:
    resources = (
        (
            "AUDIT_RESULT_SCHEMA",
            "audit-result-v1.schema.json",
            audit_result_v1_text,
            "title",
            "Lacuna audit result v1",
        ),
        (
            "BUNDLE_MANIFEST_SCHEMA",
            "lacuna-bundle-manifest-v1.schema.json",
            bundle_manifest_v1_text,
            "title",
            "Lacuna reproducibility bundle manifest v1",
        ),
        (
            "PERSISTED_ARTIFACT_COMPATIBILITY",
            "persisted-artifact-compatibility-v1.json",
            persisted_artifact_compatibility_v1_text,
            "format",
            "lacuna.persisted-artifact-compatibility",
        ),
        (
            "STANDARD_AUDIT_PROFILE_SCHEMA",
            "standard-audit-profile-v1.schema.json",
            standard_audit_profile_v1_text,
            "title",
            "Lacuna standardized audit profile v1",
        ),
    )
    checks: list[DiagnosticCheck] = []
    for code, resource, loader, field_name, expected in resources:
        try:
            payload = json.loads(loader())
            valid = isinstance(payload, dict) and payload.get(field_name) == expected
        except (OSError, UnicodeError, json.JSONDecodeError):
            valid = False
        checks.append(
            _check(
                code,
                DiagnosticState.PASS if valid else DiagnosticState.FAIL,
                (
                    f"Packaged resource {resource} is readable and has the expected identity."
                    if valid
                    else f"Packaged resource {resource} is missing or invalid; reinstall the wheel."
                ),
                resource=resource,
            )
        )
    return tuple(checks)


def diagnose_installation() -> InstallationDiagnostics:
    """Inspect the installed runtime without reading user data or activating plugins."""

    checks: list[DiagnosticCheck] = []
    package_version_valid = _PACKAGE_VERSION.fullmatch(__version__) is not None
    checks.append(
        _check(
            "PACKAGE_VERSION",
            DiagnosticState.PASS if package_version_valid else DiagnosticState.FAIL,
            (
                "The Python package exposes a valid release version."
                if package_version_valid
                else "The Python package version is invalid; reinstall an official release wheel."
            ),
            package_version=__version__,
        )
    )

    installed_version = _distribution_metadata_version(_CORE_DISTRIBUTION)
    if installed_version is None:
        distribution_state = DiagnosticState.WARN
        distribution_message = (
            "Distribution metadata is unavailable; source-tree use can continue, but wheel "
            "identity is not established."
        )
    elif installed_version != __version__:
        distribution_state = DiagnosticState.FAIL
        distribution_message = (
            "Distribution metadata and package source versions differ; reinstall one "
            "matching wheel."
        )
    else:
        distribution_state = DiagnosticState.PASS
        distribution_message = "Distribution metadata matches the Python package version."
    checks.append(
        _check(
            "DISTRIBUTION_METADATA",
            distribution_state,
            distribution_message,
            distribution_version=installed_version,
            package_version=__version__,
        )
    )

    conflicting_version = _distribution_metadata_version(_CONFLICTING_DISTRIBUTION)
    checks.append(
        _check(
            "DISTRIBUTION_NAME_COLLISION",
            (DiagnosticState.PASS if conflicting_version is None else DiagnosticState.FAIL),
            (
                "No conflicting distribution owns the lacuna import package."
                if conflicting_version is None
                else (
                    "A distribution named lacuna is also installed; uninstall it before using "
                    "lacuna-quant to avoid ambiguous ownership of the lacuna import package."
                )
            ),
            conflicting_distribution=_CONFLICTING_DISTRIBUTION,
            conflicting_version=conflicting_version,
        )
    )

    current_python = sys.version_info[:2]
    if current_python < MINIMUM_PYTHON:
        python_state = DiagnosticState.FAIL
        python_message = "Python 3.11 or newer is required."
    elif current_python not in TESTED_PYTHON:
        python_state = DiagnosticState.WARN
        python_message = "This Python minor is outside the release-tested 3.11-3.14 matrix."
    else:
        python_state = DiagnosticState.PASS
        python_message = "The Python minor is inside the release-tested compatibility matrix."
    checks.append(
        _check(
            "PYTHON_RUNTIME",
            python_state,
            python_message,
            current=f"{current_python[0]}.{current_python[1]}",
            minimum="3.11",
            tested=tuple(f"{major}.{minor}" for major, minor in TESTED_PYTHON),
        )
    )

    system = platform.system()
    machine = platform.machine().casefold()
    platform_supported = (system, machine) in _SUPPORTED_WHEELS
    checks.append(
        _check(
            "PLATFORM_WHEEL",
            DiagnosticState.PASS if platform_supported else DiagnosticState.WARN,
            (
                "The runtime matches a target-smoke-tested wheel platform."
                if platform_supported
                else "This runtime is outside the published wheel matrix; use is source-build only."
            ),
            machine=machine,
            system=system,
        )
    )

    dependency_versions = {
        "numpy": _distribution_metadata_version("numpy"),
        "polars": _distribution_metadata_version("polars"),
        "lacuna_options": _distribution_metadata_version("lacuna-options"),
    }
    dependency_valid = (
        dependency_versions["numpy"] == np.__version__
        and dependency_versions["polars"] == pl.__version__
    )
    checks.append(
        _check(
            "RUNTIME_DEPENDENCIES",
            DiagnosticState.PASS if dependency_valid else DiagnosticState.FAIL,
            (
                "Required dependency metadata matches the imported runtimes."
                if dependency_valid
                else (
                    "NumPy or Polars metadata differs from the imported runtime; "
                    "reinstall dependencies."
                )
            ),
            numpy_import=np.__version__,
            numpy_metadata=dependency_versions["numpy"],
            polars_import=pl.__version__,
            polars_metadata=dependency_versions["polars"],
        )
    )

    native, native_check = _native_check()
    checks.append(native_check)
    checks.extend(_schema_checks())

    configuration: Config | None = None
    try:
        configuration = get_config()
    except ConfigurationError as error:
        checks.append(
            _check(
                "RUNTIME_CONFIGURATION",
                DiagnosticState.FAIL,
                "Runtime configuration is invalid; correct the documented LACUNA_* settings.",
                error_type=type(error).__name__,
            )
        )
    if configuration is not None:
        checks.append(
            _check(
                "RUNTIME_CONFIGURATION",
                DiagnosticState.PASS,
                "Runtime configuration resolved successfully.",
                threads=configuration.threads,
            )
        )

    runtime: dict[str, JsonValue] = {
        "implementation": platform.python_implementation(),
        "machine": machine,
        "system": system,
        "supported_python_minimum": "3.11",
        "tested_python_minors": tuple(f"{major}.{minor}" for major, minor in TESTED_PYTHON),
    }
    return InstallationDiagnostics(
        checks=tuple(sorted(checks, key=lambda item: item.code)),
        distribution_version=installed_version,
        native=native,
        configuration=_configuration_payload(configuration),
        dependencies=dependency_versions,
        runtime=runtime,
    )


__all__ = [
    "DIAGNOSTIC_VERSION",
    "DiagnosticCheck",
    "DiagnosticState",
    "InstallationDiagnostics",
    "diagnose_installation",
]
