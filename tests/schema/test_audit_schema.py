from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker, ValidationError

ROOT = Path(__file__).parents[2]
SCHEMA_PATH = ROOT / "schemas" / "audit-result-v1.schema.json"
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "audit-result-v1.json"


def _validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def test_persisted_v1_audit_fixture_satisfies_published_schema() -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    _validator().validate(payload)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("schema_version",), "2"),
        (("metadata", "method_version"), 0),
        (("metadata", "created_at"), "not-a-date"),
        (("findings", 0, "state"), "MAYBE"),
    ],
)
def test_schema_rejects_incompatible_or_malformed_results(
    path: tuple[str | int, ...], value: object
) -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    target: object = payload
    for key in path[:-1]:
        target = target[key]  # type: ignore[index]
    target[path[-1]] = value  # type: ignore[index]

    with pytest.raises(ValidationError):
        _validator().validate(payload)
