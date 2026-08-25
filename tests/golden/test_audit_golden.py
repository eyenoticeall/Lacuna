from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from lacuna.report import AuditReport
from lacuna.types import AnalysisResult, Finding, FindingState, ResultMetadata, Severity

ROOT = Path(__file__).parents[2]
JSON_FIXTURE = ROOT / "tests" / "fixtures" / "audit-result-v1.json"
MARKDOWN_FIXTURE = ROOT / "tests" / "fixtures" / "audit-report-v1.md"


def _representative_report() -> AuditReport:
    return AuditReport(
        AnalysisResult(
            metadata=ResultMetadata(
                method="audit.v0_1",
                method_version=1,
                parameters={
                    "not_applicable_policy": "excluded",
                    "score_version": 1,
                    "unknown_credit": 0.0,
                    "warn_credit": 0.5,
                },
                seed=42,
                input_fingerprint="sha256:fixture-v1",
                created_at=datetime(2026, 8, 26, 12, 0, tzinfo=UTC),
            ),
            metrics={
                "robustness_score": 80.0,
                "evidence_coverage": 0.8,
                "earned_weight": 80.0,
                "possible_weight": 100.0,
                "unknown_weight": 20.0,
                "finding_count": 2,
                "failure_count": 0,
                "warning_count": 0,
                "unknown_count": 1,
                "not_applicable_count": 0,
            },
            findings=(
                Finding(
                    code="IC_DEFINED",
                    title="Information coefficient is defined",
                    message="The IC time series contains a defined aggregate correlation.",
                    state=FindingState.PASS,
                    severity=Severity.HIGH,
                    category="statistical_validity",
                    evidence={"mean_ic": 0.04, "rule_version": 1, "weight": 12.0},
                ),
                Finding(
                    code="TRIAL_HISTORY_AVAILABLE",
                    title="Research trial history is available",
                    message="experiment trial history was not supplied",
                    state=FindingState.UNKNOWN,
                    severity=Severity.HIGH,
                    category="experiment_integrity",
                    evidence={"rule_version": 1, "weight": 2.0},
                ),
            ),
            tables={
                "finding_summary": (
                    {"count": 1, "state": "PASS"},
                    {"count": 1, "state": "UNKNOWN"},
                ),
                "score_components": (
                    {
                        "category": "statistical_validity",
                        "earned_weight": 80.0,
                        "possible_weight": 100.0,
                        "score": 80.0,
                        "unknown_weight": 20.0,
                    },
                ),
            },
            warnings=("Representative compatibility fixture; values are illustrative.",),
            schema_version="1",
        )
    )


def test_canonical_json_matches_v1_golden_fixture() -> None:
    assert _representative_report().to_json() + "\n" == JSON_FIXTURE.read_text(encoding="utf-8")


def test_markdown_matches_v1_golden_fixture() -> None:
    assert _representative_report().to_markdown() == MARKDOWN_FIXTURE.read_text(encoding="utf-8")
