from __future__ import annotations

import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from lacuna import AnalysisResult, AuditProfile, BundleManifest
from lacuna.schemas import persisted_artifact_compatibility_v1_text

ROOT = Path(__file__).parents[2]
COMPATIBILITY_PATH = ROOT / "schemas" / "persisted-artifact-compatibility-v1.json"
CORPUS_PATH = ROOT / "tests" / "fixtures" / "persisted-artifact-corpus-v1.json"

EXPECTED_RELEASES = {
    "analysis_result": [
        "v0.1.0",
        "v0.2.0",
        "v0.3.0",
        "v0.4.0",
        "v0.5.0",
        "v0.6.0",
        "v0.7.0",
        "v0.8.0",
    ],
    "reproducibility_bundle": ["v0.7.0", "v0.8.0"],
    "standard_audit_profile": ["v0.8.0"],
}

SCHEMAS = {
    "analysis_result": ROOT / "schemas" / "audit-result-v1.schema.json",
    "reproducibility_bundle": ROOT / "schemas" / "lacuna-bundle-manifest-v1.schema.json",
    "standard_audit_profile": ROOT / "schemas" / "standard-audit-profile-v1.schema.json",
}


def _git_blob_sha1(content: bytes) -> str:
    header = f"blob {len(content)}\0".encode()
    return hashlib.sha1(header + content, usedforsecurity=False).hexdigest()


def _compatibility_contracts() -> dict[str, dict[str, object]]:
    payload = json.loads(COMPATIBILITY_PATH.read_text(encoding="utf-8"))
    assert payload["format"] == "lacuna.persisted-artifact-compatibility"
    assert payload["manifest_version"] == 1
    assert payload["consumer_package_series"] == "0.9"
    contracts = payload["contracts"]
    assert isinstance(contracts, list)
    indexed = {item["artifact"]: item for item in contracts}
    assert set(indexed) == set(EXPECTED_RELEASES)
    return indexed


def test_published_and_packaged_compatibility_manifests_are_identical() -> None:
    assert persisted_artifact_compatibility_v1_text() == COMPATIBILITY_PATH.read_text(
        encoding="utf-8"
    )


def test_compatibility_manifest_declares_only_reviewed_identity_routes() -> None:
    contracts = _compatibility_contracts()
    assert contracts["analysis_result"]["producer_package_series"] == [
        "0.1",
        "0.2",
        "0.3",
        "0.4",
        "0.5",
        "0.6",
        "0.7",
        "0.8",
        "0.9",
    ]
    assert contracts["reproducibility_bundle"]["producer_package_series"] == [
        "0.7",
        "0.8",
        "0.9",
    ]
    assert contracts["standard_audit_profile"]["producer_package_series"] == [
        "0.8",
        "0.9",
    ]
    for contract in contracts.values():
        assert contract["source_version"] == "1"
        assert contract["target_version"] == "1"
        assert contract["migration"] == "identity"


def test_every_tagged_persisted_fixture_remains_hash_identical_and_readable() -> None:
    contracts = _compatibility_contracts()
    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    assert corpus["format"] == "lacuna.persisted-artifact-corpus"
    assert corpus["manifest_version"] == 1
    artifacts = corpus["artifacts"]
    assert isinstance(artifacts, list)
    assert {item["artifact"] for item in artifacts} == set(EXPECTED_RELEASES)

    for item in artifacts:
        artifact = item["artifact"]
        assert isinstance(artifact, str)
        assert item["release_tags"] == EXPECTED_RELEASES[artifact]
        assert item["source_version"] == contracts[artifact]["source_version"]
        assert item["migration"] == contracts[artifact]["migration"]

        relative_path = item["path"]
        assert isinstance(relative_path, str)
        path = ROOT / relative_path
        assert path.is_relative_to(ROOT)
        content = path.read_bytes()
        assert hashlib.sha256(content).hexdigest() == item["sha256"]
        assert _git_blob_sha1(content) == item["git_blob_sha1"]

        payload = json.loads(content)
        schema = json.loads(SCHEMAS[artifact].read_text(encoding="utf-8"))
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(payload)
        if artifact == "analysis_result":
            assert item["reader"] == "lacuna.AnalysisResult.from_json"
            assert AnalysisResult.from_json(content.decode()).to_dict() == payload
        elif artifact == "reproducibility_bundle":
            assert item["reader"] == "lacuna.BundleManifest.from_json"
            assert BundleManifest.from_json(content.decode()).to_dict() == payload
        else:
            assert item["reader"] == "lacuna.AuditProfile.from_json"
            assert AuditProfile.from_json(content.decode()).to_dict() == payload
