from __future__ import annotations

import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

from lacuna.report import AuditReport
from lacuna.schemas import bundle_manifest_v1_text
from lacuna.types import AnalysisResult, ResultMetadata

ROOT = Path(__file__).parents[2]
SCHEMA_PATH = ROOT / "schemas" / "lacuna-bundle-manifest-v1.schema.json"
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "bundle-manifest-v1.json"


def _validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def test_persisted_bundle_manifest_fixture_satisfies_published_schema() -> None:
    _validator().validate(json.loads(FIXTURE_PATH.read_text(encoding="utf-8")))


def test_packaged_bundle_schema_matches_language_independent_source() -> None:
    assert bundle_manifest_v1_text() == SCHEMA_PATH.read_text(encoding="utf-8")


def test_created_bundle_manifest_satisfies_published_schema(tmp_path: Path) -> None:
    report = AuditReport(
        AnalysisResult(
            metadata=ResultMetadata(
                method="audit.schema_fixture",
                created_at=datetime(2026, 8, 26, tzinfo=UTC),
            )
        )
    )
    path = report.bundle(tmp_path / "schema.lacuna")
    with zipfile.ZipFile(path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    _validator().validate(manifest)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("bundle_version",), 2),
        (("format",), "unknown"),
        (("artifacts", 0, "path"), "../escape"),
        (("security", "plugins_activated"), True),
        (("reproducibility", "level"), "bitwise_reproducible"),
    ],
)
def test_schema_rejects_incompatible_or_unsafe_manifests(
    path: tuple[str | int, ...], value: object
) -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    target: object = payload
    for key in path[:-1]:
        target = target[key]  # type: ignore[index]
    target[path[-1]] = value  # type: ignore[index]

    with pytest.raises(ValidationError):
        _validator().validate(payload)
