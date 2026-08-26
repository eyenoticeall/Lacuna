from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from lacuna.audit import AuditContext
from lacuna.audit_profiles import (
    AuditProfile,
    AuditScope,
    EvidenceDisposition,
    EvidenceRequirement,
    run_standard_audit,
    standard_audit,
    standard_profile,
)
from lacuna.types import AnalysisResult, Finding, FindingState, ResultMetadata, Severity

CREATED_AT = datetime(2026, 8, 26, tzinfo=UTC)


def _result(
    method: str,
    *,
    findings: tuple[Finding, ...] = (),
    seed: int | None = None,
    fingerprint: str | None = None,
) -> AnalysisResult:
    return AnalysisResult(
        metadata=ResultMetadata(
            method=method,
            seed=seed,
            input_fingerprint=fingerprint,
            created_at=CREATED_AT,
        ),
        findings=findings,
    )


def _finding(
    code: str,
    state: FindingState,
    *,
    severity: Severity = Severity.MEDIUM,
) -> Finding:
    return Finding(
        code=code,
        title=f"{code} title",
        message=f"{code} message",
        state=state,
        severity=severity,
        category="source_category",
        evidence={"threshold": 0.25},
    )


def test_standard_profiles_make_scope_applicability_explicit() -> None:
    signal = {
        item.capability_id: item.disposition for item in standard_profile("signal").requirements
    }
    strategy = {
        item.capability_id: item.disposition for item in standard_profile("strategy").requirements
    }
    options = {
        item.capability_id: item.disposition for item in standard_profile("options").requirements
    }

    assert signal["signal_diagnostics"] == EvidenceDisposition.REQUIRED
    assert signal["execution_realism"] == EvidenceDisposition.NOT_APPLICABLE
    assert strategy["signal_diagnostics"] == EvidenceDisposition.OPTIONAL
    assert strategy["execution_realism"] == EvidenceDisposition.REQUIRED
    assert strategy["options_evidence"] == EvidenceDisposition.NOT_APPLICABLE
    assert options["options_evidence"] == EvidenceDisposition.REQUIRED


def test_empty_standard_audit_exposes_required_coverage_without_a_score() -> None:
    result = run_standard_audit(AuditContext(), scope="strategy")

    assert result.metadata.method == "audit.standard"
    assert result.metadata.parameters["score_model"] is None
    assert "robustness_score" not in result.metrics
    assert result.metrics["required_evidence_coverage"] == 0.0
    assert result.metrics["required_evidence_complete"] is False
    assert result.metrics["unknown_count"] == result.metrics["required_capability_count"]
    assert result.metrics["not_applicable_count"] == 4
    assert result.warnings[0].startswith("The standardized profile computes evidence coverage")


def test_domain_findings_are_propagated_without_threshold_or_state_changes() -> None:
    source = _finding("COST_STRESS_FAIL", FindingState.FAIL, severity=Severity.CRITICAL)
    result = run_standard_audit(
        AuditContext(
            results={
                "cost-stress": _result(
                    "costs.stress",
                    findings=(source,),
                    seed=7,
                    fingerprint="sha256:costs",
                )
            }
        ),
        scope="strategy",
    )

    propagated = next(
        finding
        for finding in result.findings
        if finding.evidence.get("source_finding_code") == "COST_STRESS_FAIL"
    )
    assert propagated.state == source.state
    assert propagated.severity == source.severity
    assert propagated.title == source.title
    assert propagated.message == source.message
    assert propagated.evidence["source_evidence"] == source.evidence
    assert propagated.evidence["propagated_without_reinterpretation"] is True
    assert result.metrics["failure_count"] == 1

    inventory = result.table("evidence_inventory")
    assert inventory == [
        {
            "source_name": "cost-stress",
            "method": "costs.stress",
            "method_version": 1,
            "schema_version": "1",
            "capability": "execution_realism",
            "disposition": "required",
            "recognized": True,
            "finding_count": 1,
            "warning_count": 0,
            "has_seed": True,
            "has_input_fingerprint": True,
        }
    ]


def test_recognized_result_order_does_not_change_normalized_output() -> None:
    evidence = {
        "split": _result("cv.purged_kfold"),
        "bias": _result(
            "bias.future_data_check", findings=(_finding("NO_FUTURE", FindingState.PASS),)
        ),
        "adapter": _result("adapters.vendor_schema"),
    }
    forward = run_standard_audit(AuditContext(results=evidence), scope=AuditScope.STRATEGY)
    reverse = run_standard_audit(
        AuditContext(results=dict(reversed(tuple(evidence.items())))),
        scope=AuditScope.STRATEGY,
    )

    assert forward.metrics == reverse.metrics
    assert forward.tables == reverse.tables
    assert [item.to_dict() for item in forward.findings] == [
        item.to_dict() for item in reverse.findings
    ]


def test_unrecognized_and_scope_inconsistent_evidence_remain_visible() -> None:
    result = run_standard_audit(
        AuditContext(
            results={
                "unknown": _result("future.unrecognized_method"),
                "costs": _result("costs.stress"),
            }
        ),
        scope="signal",
    )
    states = {finding.code: finding.state for finding in result.findings}

    assert states["UNRECOGNIZED_EVIDENCE"] == FindingState.WARN
    assert states["EVIDENCE_EXECUTION_REALISM"] == FindingState.WARN
    assert result.metrics["unrecognized_result_count"] == 1
    inventory = result.table("evidence_inventory")
    assert isinstance(inventory, list)
    assert next(row for row in inventory if row["source_name"] == "unknown")["recognized"] is False


def test_custom_profile_overlap_and_scope_mismatch_fail_closed() -> None:
    first = EvidenceRequirement(
        capability_id="first",
        title="First",
        category="operational",
        methods=("shared.*",),
        disposition=EvidenceDisposition.REQUIRED,
    )
    second = EvidenceRequirement(
        capability_id="second",
        title="Second",
        category="operational",
        methods=("shared.method",),
        disposition=EvidenceDisposition.OPTIONAL,
    )
    profile = AuditProfile(
        profile_id="custom.strategy",
        profile_version=1,
        scope=AuditScope.STRATEGY,
        requirements=(first, second),
    )
    with pytest.raises(ValueError, match="matches multiple"):
        run_standard_audit(
            AuditContext(results={"shared": _result("shared.method")}),
            profile=profile,
        )
    with pytest.raises(ValueError, match="profile scope"):
        run_standard_audit(AuditContext(), scope="signal", profile=profile)
    with pytest.raises(ValueError, match="study_type"):
        run_standard_audit(
            AuditContext(policies={"study_type": "signal"}),
            scope="strategy",
        )


def test_custom_profile_identifiers_versions_and_method_tuples_are_validated() -> None:
    with pytest.raises(TypeError, match="non-empty tuple"):
        EvidenceRequirement(
            capability_id="bad_methods",
            title="Bad methods",
            category="operational",
            methods=["custom.*"],  # type: ignore[arg-type]
            disposition=EvidenceDisposition.REQUIRED,
        )
    requirement = EvidenceRequirement(
        capability_id="custom",
        title="Custom",
        category="operational",
        methods=("custom.*",),
        disposition=EvidenceDisposition.REQUIRED,
    )
    with pytest.raises(ValueError, match="profile_id"):
        AuditProfile("Invalid Profile", 1, AuditScope.STRATEGY, (requirement,))
    with pytest.raises(ValueError, match="positive integer"):
        AuditProfile("custom.strategy", True, AuditScope.STRATEGY, (requirement,))


def test_profile_v1_strict_reader_round_trips_without_executing_content() -> None:
    profile = standard_profile("options")

    assert AuditProfile.from_dict(profile.to_dict()) == profile
    assert AuditProfile.from_json(json.dumps(profile.to_dict())) == profile


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ('{"schema_version":"1","schema_version":"1"}', "duplicate object key"),
        ('{"value":NaN}', "non-finite constant"),
        ("[]", "top level"),
    ],
)
def test_profile_v1_reader_rejects_noncanonical_or_incomplete_json(
    content: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        AuditProfile.from_json(content)


def test_profile_v1_reader_rejects_version_drift_and_unknown_fields() -> None:
    payload = standard_profile("strategy").to_dict()
    payload["schema_version"] = "2"
    with pytest.raises(ValueError, match="unsupported audit profile schema version"):
        AuditProfile.from_dict(payload)

    payload = standard_profile("strategy").to_dict()
    payload["unexpected"] = True
    with pytest.raises(ValueError, match="unexpected"):
        AuditProfile.from_dict(payload)

    payload = standard_profile("strategy").to_dict()
    requirements = payload["requirements"]
    assert isinstance(requirements, list)
    requirements[0]["disposition"] = "maybe"
    with pytest.raises(ValueError, match="unsupported disposition"):
        AuditProfile.from_dict(payload)


def test_public_wrapper_returns_a_renderable_categorical_report() -> None:
    report = standard_audit(
        results={"split": _result("cv.purged_kfold")},
        scope="strategy",
    )

    assert report.result.metadata.method == "audit.standard"
    assert report.summary()["required_evidence_coverage"] > 0.0
    markdown = report.to_markdown()
    assert "No universal score" in markdown
    assert "Required evidence coverage" in markdown
