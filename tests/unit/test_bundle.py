from __future__ import annotations

import json
import stat
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

import lacuna.bundle as bundle_module
from lacuna.bundle import BUNDLE_FORMAT, BUNDLE_VERSION, BundleManifest, verify_bundle
from lacuna.exceptions import ReportError
from lacuna.report import AuditReport
from lacuna.types import AnalysisResult, ResultMetadata


def _report(*, parameters: dict[str, object] | None = None) -> AuditReport:
    return AuditReport(
        AnalysisResult(
            metadata=ResultMetadata(
                method="audit.bundle_fixture",
                method_version=2,
                parameters=parameters or {"horizon": "5D"},
                seed=42,
                input_fingerprint="sha256:fixture",
                created_at=datetime(2026, 8, 26, tzinfo=UTC),
            ),
            metrics={
                "robustness_score": 75.0,
                "evidence_coverage": 1.0,
                "failure_count": 0,
                "warning_count": 0,
                "unknown_count": 0,
                "not_applicable_count": 0,
            },
            tables={"summary": ({"value": 1.0},)},
        )
    )


def _rewrite_archive(
    source: Path,
    destination: Path,
    *,
    replace: dict[str, bytes] | None = None,
    extra: dict[str, bytes] | None = None,
) -> None:
    with zipfile.ZipFile(source) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    members.update(replace or {})
    members.update(extra or {})
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, content in sorted(members.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o600) << 16
            archive.writestr(info, content)


def test_bundle_is_byte_stable_and_independently_verifiable(tmp_path: Path) -> None:
    first = tmp_path / "first.lacuna"
    second = tmp_path / "second.lacuna"
    report = _report()

    assert report.bundle(first) == first
    report.bundle(second)
    assert first.read_bytes() == second.read_bytes()

    verification = verify_bundle(first)
    assert verification.manifest.format == BUNDLE_FORMAT
    assert verification.manifest.bundle_version == BUNDLE_VERSION
    assert verification.manifest.report_method == "audit.bundle_fixture"
    assert verification.manifest.report_method_version == 2
    assert verification.manifest.report_input_fingerprint == "sha256:fixture"
    assert verification.artifact_count == 5
    assert verification.to_dict()["integrity_verified"] is True
    assert verification.to_dict()["authenticity_verified"] is False

    with zipfile.ZipFile(first) as archive:
        assert archive.namelist() == sorted(archive.namelist())
        assert set(archive.namelist()) == {
            "manifest.json",
            "metadata/configuration.json",
            "metadata/environment.json",
            "report/audit.html",
            "report/audit.json",
            "report/audit.md",
        }
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["security"]["source_data"] == "not_included_automatically"
        assert manifest["security"]["executable_code"] is False
        assert manifest["reproducibility"]["level"] == "identifiable"
        parsed = BundleManifest.from_json(archive.read("manifest.json").decode())
        assert BundleManifest.from_dict(manifest) == parsed
        assert parsed.to_dict() == manifest


def test_standalone_manifest_reader_rejects_duplicate_and_unsupported_content() -> None:
    with pytest.raises(ReportError, match="duplicate key"):
        BundleManifest.from_json('{"bundle_version":1,"bundle_version":1}')
    with pytest.raises(ReportError, match="fields differ"):
        BundleManifest.from_json('{"bundle_version":2}')


def test_bundle_adds_named_evidence_and_redacts_supplemental_metadata(tmp_path: Path) -> None:
    path = tmp_path / "study.lacuna"
    reordered_path = tmp_path / "study-reordered.lacuna"
    evidence = AnalysisResult(
        metadata=ResultMetadata(
            method="experiment.registry_snapshot",
            created_at=datetime(2026, 8, 26, tzinfo=UTC),
        ),
        metrics={"attempts": 3},
    )
    _report().bundle(
        path,
        configuration={
            "api_key": "do-not-package",
            "cache_dir": "/Users/researcher/private/cache",
        },
        evidence={"experiment_history": evidence},
        provenance={
            "dataset_url": "https://data.example/snapshot?signature=do-not-package#token",
            "dataset_fingerprint": "sha256:dataset",
        },
        invocation={"api": "SignalStudy.audit", "parameters": {"seed": 42}},
    )
    _report().bundle(
        reordered_path,
        configuration={
            "cache_dir": "/Users/researcher/private/cache",
            "api_key": "do-not-package",
        },
        evidence={"experiment_history": evidence},
        provenance={
            "dataset_fingerprint": "sha256:dataset",
            "dataset_url": "https://data.example/snapshot?signature=do-not-package#token",
        },
        invocation={"parameters": {"seed": 42}, "api": "SignalStudy.audit"},
    )

    assert verify_bundle(path).artifact_count == 9
    assert path.read_bytes() == reordered_path.read_bytes()
    raw = path.read_bytes()
    assert b"do-not-package" not in raw
    assert b"/Users/researcher/private/cache" not in raw
    with zipfile.ZipFile(path) as archive:
        configuration = json.loads(archive.read("metadata/configuration.json"))
        provenance = json.loads(archive.read("metadata/provenance.json"))
        redactions = json.loads(archive.read("metadata/redactions.json"))["redactions"]
        assert configuration == {
            "api_key_redacted": "<redacted>",
            "cache_dir": "<absolute-path>/cache",
        }
        assert provenance["dataset_url"] == "https://data.example/snapshot"
        assert {item["reason"] for item in redactions} == {
            "absolute_path",
            "credential_key",
            "url_credentials_or_query",
        }


@pytest.mark.parametrize(
    "parameters, message",
    [
        ({"api_token": "secret"}, "credential-bearing"),
        ({"source": "/private/data/a.parquet"}, "absolute path"),
        ({"source": "https://example/data?token=secret"}, "URL credentials"),
    ],
)
def test_bundle_rejects_unsafe_canonical_evidence(
    tmp_path: Path, parameters: dict[str, object], message: str
) -> None:
    with pytest.raises(ReportError, match=message):
        _report(parameters=parameters).bundle(tmp_path / "unsafe.lacuna")


def test_bundle_requires_safe_names_suffix_and_explicit_overwrite(tmp_path: Path) -> None:
    report = _report()
    path = tmp_path / "study.lacuna"
    report.bundle(path)

    with pytest.raises(ReportError, match="refusing to overwrite"):
        report.bundle(path)
    assert report.bundle(path, overwrite=True) == path
    with pytest.raises(ReportError, match="lacuna suffix"):
        report.bundle(tmp_path / "study.zip")
    with pytest.raises(ReportError, match="evidence names"):
        report.bundle(
            tmp_path / "bad-name.lacuna",
            evidence={"../escape": report.result},
        )


def test_verifier_rejects_tampering_extra_members_and_path_traversal(tmp_path: Path) -> None:
    source = tmp_path / "source.lacuna"
    _report().bundle(source)

    tampered = tmp_path / "tampered.lacuna"
    with zipfile.ZipFile(source) as archive:
        original_markdown = archive.read("report/audit.md")
    _rewrite_archive(
        source,
        tampered,
        replace={"report/audit.md": b"x" * len(original_markdown)},
    )
    with pytest.raises(ReportError, match="SHA-256 mismatch"):
        verify_bundle(tampered)

    extra = tmp_path / "extra.lacuna"
    _rewrite_archive(source, extra, extra={"unexpected.txt": b"unexpected"})
    with pytest.raises(ReportError, match="differ from the manifest"):
        verify_bundle(extra)

    traversal = tmp_path / "traversal.lacuna"
    _rewrite_archive(source, traversal, extra={"../escape": b"unsafe"})
    with pytest.raises(ReportError, match="unsafe member path"):
        verify_bundle(traversal)


def test_verifier_rejects_non_archives_and_noncanonical_json(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.lacuna"
    invalid.write_bytes(b"not a zip")
    with pytest.raises(ReportError, match="valid ZIP"):
        verify_bundle(invalid)

    source = tmp_path / "source.lacuna"
    malformed = tmp_path / "malformed.lacuna"
    _report().bundle(source)
    _rewrite_archive(source, malformed, replace={"manifest.json": b'{"format": "x"}\n'})
    with pytest.raises(ReportError, match="not in canonical"):
        verify_bundle(malformed)


def test_creator_enforces_verifier_member_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bundle_module, "_MAX_MEMBER_SIZE", 128)
    with pytest.raises(ReportError, match=r"member.*safety limit"):
        _report().bundle(tmp_path / "oversized.lacuna")
