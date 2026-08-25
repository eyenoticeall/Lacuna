from __future__ import annotations

import json
import math
from datetime import datetime

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
