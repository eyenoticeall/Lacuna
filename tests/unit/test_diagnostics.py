from __future__ import annotations

import json
from collections.abc import Mapping

import pytest

import lacuna.diagnostics as diagnostics
from lacuna.config import config
from lacuna.diagnostics import (
    DiagnosticCheck,
    DiagnosticState,
    InstallationDiagnostics,
    diagnose_installation,
)
from lacuna.native import NativeStatus


def _check(report: InstallationDiagnostics, code: str) -> DiagnosticCheck:
    return next(item for item in report.checks if item.code == code)


def test_diagnostics_are_versioned_ordered_and_json_serializable() -> None:
    with config(cache_dir="/private/example/lacuna-cache"):
        report = diagnose_installation()

    payload = report.to_dict()
    codes = [item.code for item in report.checks]
    assert codes == sorted(set(codes))
    assert payload["schema_version"] == "1"
    assert payload["diagnostic_version"] == 1
    assert payload["status"] in {"PASS", "WARN"}
    assert payload["healthy"] is True
    assert payload["lacuna_version"] == diagnostics.__version__
    assert payload["config"]["cache_dir"] == "<configured>"  # type: ignore[index]
    assert "/private/example" not in report.to_json()
    assert json.loads(report.to_json()) == payload


def test_diagnostic_evidence_is_deeply_immutable_and_finite() -> None:
    check = DiagnosticCheck(
        code="IMMUTABLE_EVIDENCE",
        state=DiagnosticState.PASS,
        message="Evidence is immutable.",
        evidence={"nested": {"values": [1, 2]}},
    )
    nested = check.evidence["nested"]
    assert isinstance(nested, Mapping)
    with pytest.raises(TypeError):
        nested["new"] = 3  # type: ignore[index]
    assert check.to_dict()["evidence"] == {"nested": {"values": [1, 2]}}

    with pytest.raises(ValueError, match="NaN or infinity"):
        DiagnosticCheck(
            code="NONFINITE",
            state=DiagnosticState.FAIL,
            message="Invalid evidence.",
            evidence={"value": float("nan")},
        )


def test_distribution_version_mismatch_is_actionable_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actual = diagnostics._distribution_metadata_version

    def mismatched(name: str) -> str | None:
        return "999.0.0" if name == "lacuna" else actual(name)

    monkeypatch.setattr(diagnostics, "_distribution_metadata_version", mismatched)
    report = diagnose_installation()
    check = _check(report, "DISTRIBUTION_METADATA")

    assert report.status == DiagnosticState.FAIL
    assert check.state == DiagnosticState.FAIL
    assert "reinstall one matching wheel" in check.message


def test_unavailable_native_core_fails_without_leaking_raw_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        diagnostics,
        "native_status",
        lambda: NativeStatus(False, None, "/private/secret/native-loader-detail"),
    )
    report = diagnose_installation()
    payload = report.to_json()

    assert report.status == DiagnosticState.FAIL
    assert _check(report, "NATIVE_CORE").state == DiagnosticState.FAIL
    assert "native-loader-detail" not in payload
    assert "/private/secret" not in payload


def test_invalid_packaged_schema_is_identified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(diagnostics, "audit_result_v1_text", lambda: "{}")
    report = diagnose_installation()

    check = _check(report, "AUDIT_RESULT_SCHEMA")
    assert check.state == DiagnosticState.FAIL
    assert "reinstall the wheel" in check.message


def test_unsupported_wheel_platform_is_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(diagnostics.platform, "system", lambda: "Plan9")
    monkeypatch.setattr(diagnostics.platform, "machine", lambda: "mips")
    report = diagnose_installation()

    check = _check(report, "PLATFORM_WHEEL")
    assert check.state == DiagnosticState.WARN
    assert report.healthy is True


def test_diagnosis_does_not_discover_or_activate_plugins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import lacuna.plugins as plugins

    def unexpected_discovery(*args: object, **kwargs: object) -> object:
        raise AssertionError("diagnostics must not inspect plugins")

    monkeypatch.setattr(plugins, "discover_plugins", unexpected_discovery)
    diagnose_installation()
