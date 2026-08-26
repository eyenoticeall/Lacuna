from __future__ import annotations

import json
import math
from datetime import UTC, datetime

import pytest

from lacuna import AnalysisResult, Finding, FindingState, ResultMetadata, Severity


def test_result_is_structured_and_json_serializable() -> None:
    result = AnalysisResult(
        metadata=ResultMetadata(
            method="signal.ic",
            parameters={"horizons": ["1D", "5D"]},
            seed=7,
        ),
        metrics={"mean_ic": 0.031},
        findings=(
            Finding(
                code="TRIAL_HISTORY_MISSING",
                title="Trial history unavailable",
                message="Multiple-testing risk cannot be estimated.",
                state=FindingState.UNKNOWN,
                severity=Severity.HIGH,
                category="research_process",
            ),
        ),
    )

    payload = json.loads(result.to_json())
    assert payload["schema_version"] == "1"
    assert payload["metrics"]["mean_ic"] == 0.031
    assert payload["findings"][0]["state"] == "UNKNOWN"
    assert payload["metadata"]["parameters"]["horizons"] == ["1D", "5D"]


def test_nested_result_mappings_are_immutable() -> None:
    result = AnalysisResult(
        metadata=ResultMetadata(method="test"),
        metrics={"nested": {"value": 1}},
    )

    nested = result.metrics["nested"]
    assert isinstance(nested, dict | type(result.metrics))
    with pytest.raises(TypeError):
        nested["value"] = 2  # type: ignore[index]


def test_result_rejects_non_json_values() -> None:
    with pytest.raises(TypeError, match="JSON-compatible"):
        AnalysisResult(
            metadata=ResultMetadata(method="test"),
            metrics={"bad": object()},  # type: ignore[dict-item]
        )


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_result_rejects_non_finite_numbers(value: float) -> None:
    with pytest.raises(ValueError, match="NaN or infinity"):
        AnalysisResult(
            metadata=ResultMetadata(method="test"),
            metrics={"bad": value},
        )


def test_metadata_requires_timezone_aware_creation_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        ResultMetadata(method="test", created_at=datetime(2026, 8, 25))


def test_result_strict_json_reader_round_trips_the_v1_envelope() -> None:
    original = AnalysisResult(
        metadata=ResultMetadata(
            method="test.round_trip",
            method_version=2,
            parameters={"nested": {"value": 3}},
            seed=7,
            input_fingerprint="sha256:fixture",
            created_at=datetime(2026, 8, 26, tzinfo=UTC),
        ),
        metrics={"score": 0.5},
        findings=(
            Finding(
                code="ROUND_TRIP",
                title="Round trip",
                message="The result survives strict parsing.",
                state=FindingState.PASS,
                severity=Severity.INFO,
                evidence={"threshold": 0.25},
            ),
        ),
        tables={"rows": ({"value": 1},)},
        warnings=("illustrative warning",),
    )

    parsed = AnalysisResult.from_json(original.to_json())
    assert parsed.to_dict() == original.to_dict()
    assert AnalysisResult.from_dict(original.to_dict()).to_dict() == original.to_dict()


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ('{"schema_version":"1","schema_version":"1"}', "duplicate object key"),
        ('{"value":NaN}', "non-finite constant"),
        ("[]", "top level"),
        ('{"schema_version":"2"}', "fields do not match v1"),
    ],
)
def test_result_strict_json_reader_rejects_noncanonical_or_incomplete_input(
    content: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        AnalysisResult.from_json(content)


def test_result_strict_reader_rejects_unknown_fields_and_unsupported_values() -> None:
    payload = AnalysisResult(
        metadata=ResultMetadata(method="test.strict", created_at=datetime(2026, 8, 26, tzinfo=UTC))
    ).to_dict()
    payload["unexpected"] = True
    with pytest.raises(ValueError, match="unexpected"):
        AnalysisResult.from_dict(payload)

    invalid = json.loads(
        json.dumps({key: value for key, value in payload.items() if key != "unexpected"})
    )
    invalid["metadata"]["created_at"] = "2026-08-26T00:00:00+00:00"
    with pytest.raises(ValueError, match="ending in Z"):
        AnalysisResult.from_dict(invalid)

    invalid["metadata"]["created_at"] = "2026-08-26T00:00:00Z"
    invalid["findings"] = [
        {
            "code": "BAD",
            "title": "Bad state",
            "message": "Unsupported state",
            "state": "MAYBE",
            "severity": "high",
            "category": "test",
            "evidence": {},
        }
    ]
    with pytest.raises(ValueError, match="unsupported state"):
        AnalysisResult.from_dict(invalid)
