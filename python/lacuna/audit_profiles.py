"""Versioned cross-phase audit profiles over immutable Lacuna evidence."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from math import isfinite
from numbers import Integral
from types import MappingProxyType
from typing import cast

from lacuna.audit import AuditContext
from lacuna.report import AuditReport
from lacuna.types import (
    AnalysisResult,
    Finding,
    FindingState,
    JsonValue,
    ResultMetadata,
    Severity,
)


class AuditScope(StrEnum):
    """Research boundary selected by a standardized audit profile."""

    SIGNAL = "signal"
    STRATEGY = "strategy"
    OPTIONS = "options"


class EvidenceDisposition(StrEnum):
    """Whether one evidence capability is required by a profile."""

    REQUIRED = "required"
    OPTIONAL = "optional"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True, slots=True)
class EvidenceRequirement:
    """One method-family capability in a versioned audit profile."""

    capability_id: str
    title: str
    category: str
    methods: tuple[str, ...]
    disposition: EvidenceDisposition
    severity: Severity = Severity.HIGH

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, str) or not value
            for value in (self.capability_id, self.title, self.category)
        ):
            raise ValueError("evidence requirement identifiers and descriptions must not be empty")
        if not re.fullmatch(r"[a-z][a-z0-9_]*", self.capability_id):
            raise ValueError("capability_id must use lowercase letters, digits, and underscores")
        if not isinstance(self.methods, tuple) or not self.methods:
            raise TypeError("evidence requirement methods must be a non-empty tuple")
        if any(not isinstance(method, str) or not method for method in self.methods):
            raise ValueError("evidence requirement methods must not be empty")
        if len(self.methods) != len(set(self.methods)):
            raise ValueError("evidence requirement methods must be unique")
        if any("*" in method[:-1] or method.count("*") > 1 for method in self.methods):
            raise ValueError("method patterns may use one trailing wildcard only")
        if not isinstance(self.disposition, EvidenceDisposition):
            raise TypeError("disposition must be an EvidenceDisposition")
        if not isinstance(self.severity, Severity):
            raise TypeError("severity must be a Severity")
        object.__setattr__(self, "methods", tuple(self.methods))

    def matches(self, method: str) -> bool:
        """Return whether a result method belongs to this capability."""

        return any(
            method.startswith(pattern[:-1]) if pattern.endswith("*") else method == pattern
            for pattern in self.methods
        )


@dataclass(frozen=True, slots=True)
class AuditProfile:
    """Immutable scope-specific standardized-audit contract."""

    profile_id: str
    profile_version: int
    scope: AuditScope
    requirements: tuple[EvidenceRequirement, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.profile_id, str)
            or re.fullmatch(r"[a-z][a-z0-9_.-]*", self.profile_id) is None
        ):
            raise ValueError(
                "profile_id must use lowercase letters, digits, dots, underscores, and hyphens"
            )
        if (
            isinstance(self.profile_version, bool)
            or not isinstance(self.profile_version, int)
            or self.profile_version < 1
        ):
            raise ValueError("profile_version must be a positive integer")
        if not isinstance(self.scope, AuditScope):
            raise TypeError("scope must be an AuditScope")
        if not isinstance(self.requirements, tuple) or not self.requirements:
            raise ValueError("an audit profile must contain at least one evidence requirement")
        if any(not isinstance(item, EvidenceRequirement) for item in self.requirements):
            raise TypeError("requirements must contain EvidenceRequirement values")
        identifiers = [item.capability_id for item in self.requirements]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("profile capability identifiers must be unique")
        object.__setattr__(self, "requirements", tuple(self.requirements))

    def to_dict(self) -> dict[str, object]:
        """Return the profile's portable schema-v1 representation."""

        return {
            "schema_version": "1",
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "scope": self.scope.value,
            "scoring_model": None,
            "coverage_rule_version": 1,
            "requirements": [
                {
                    "capability": requirement.capability_id,
                    "title": requirement.title,
                    "category": requirement.category,
                    "disposition": requirement.disposition.value,
                    "accepted_methods": list(requirement.methods),
                    "missing_severity": requirement.severity.value,
                }
                for requirement in self.requirements
            ],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> AuditProfile:
        """Parse the strict supported profile-v1 definition without executing content."""

        if cls is not AuditProfile:
            raise TypeError("AuditProfile.from_dict does not construct subclasses")
        return _audit_profile_from_dict(value)

    @classmethod
    def from_json(cls, value: str) -> AuditProfile:
        """Parse finite profile-v1 JSON while rejecting duplicate keys at every depth."""

        if cls is not AuditProfile:
            raise TypeError("AuditProfile.from_json does not construct subclasses")
        if not isinstance(value, str):
            raise TypeError("audit profile JSON must be a string")

        def reject_constant(constant: str) -> object:
            raise ValueError(f"audit profile JSON contains non-finite constant {constant!r}")

        def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, item in pairs:
                if key in result:
                    raise ValueError(f"audit profile JSON contains duplicate object key {key!r}")
                result[key] = item
            return result

        try:
            parsed = json.loads(
                value,
                parse_constant=reject_constant,
                object_pairs_hook=unique_object,
            )
        except json.JSONDecodeError as error:
            raise ValueError(f"invalid audit profile JSON: {error.msg}") from error
        if not isinstance(parsed, Mapping):
            raise ValueError("audit profile JSON must contain an object at the top level")
        return _audit_profile_from_dict(parsed)


def _strict_profile_object(
    value: object,
    *,
    name: str,
    required: set[str],
) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise ValueError(f"{name} keys must be strings")
    typed = cast(Mapping[str, object], value)
    observed = set(typed)
    missing = sorted(required - observed)
    extra = sorted(observed - required)
    if missing or extra:
        raise ValueError(
            f"{name} fields do not match profile v1: missing={missing}, unexpected={extra}"
        )
    return typed


def _profile_positive_integer(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return int(value)


def _audit_profile_from_dict(value: Mapping[str, object]) -> AuditProfile:
    payload = _strict_profile_object(
        value,
        name="audit profile",
        required={
            "schema_version",
            "profile_id",
            "profile_version",
            "scope",
            "scoring_model",
            "coverage_rule_version",
            "requirements",
        },
    )
    if payload["schema_version"] != "1":
        raise ValueError(f"unsupported audit profile schema version {payload['schema_version']!r}")
    if payload["scoring_model"] is not None:
        raise ValueError("audit profile v1 scoring_model must be null")
    if (
        _profile_positive_integer(
            payload["coverage_rule_version"], name="audit profile coverage_rule_version"
        )
        != 1
    ):
        raise ValueError("audit profile v1 coverage_rule_version must be 1")

    profile_id = payload["profile_id"]
    if not isinstance(profile_id, str):
        raise ValueError("audit profile profile_id must be a string")
    scope_raw = payload["scope"]
    try:
        scope = AuditScope(scope_raw) if isinstance(scope_raw, str) else None
    except ValueError as error:
        raise ValueError("audit profile has an unsupported scope") from error
    if scope is None:
        raise ValueError("audit profile has an unsupported scope")

    requirements_raw = payload["requirements"]
    if not isinstance(requirements_raw, Sequence) or isinstance(requirements_raw, str | bytes):
        raise ValueError("audit profile requirements must be an array")
    requirements: list[EvidenceRequirement] = []
    for index, raw_requirement in enumerate(requirements_raw):
        item = _strict_profile_object(
            raw_requirement,
            name=f"audit profile requirement {index}",
            required={
                "capability",
                "title",
                "category",
                "disposition",
                "accepted_methods",
                "missing_severity",
            },
        )
        strings: dict[str, str] = {}
        for key in ("capability", "title", "category"):
            item_value = item[key]
            if not isinstance(item_value, str) or not item_value:
                raise ValueError(
                    f"audit profile requirement {index} {key} must be a non-empty string"
                )
            strings[key] = item_value

        methods_raw = item["accepted_methods"]
        if not isinstance(methods_raw, Sequence) or isinstance(methods_raw, str | bytes):
            raise ValueError(f"audit profile requirement {index} accepted_methods must be an array")
        if any(not isinstance(method, str) for method in methods_raw):
            raise ValueError(
                f"audit profile requirement {index} accepted_methods must contain strings"
            )
        disposition_raw = item["disposition"]
        try:
            disposition = (
                EvidenceDisposition(disposition_raw) if isinstance(disposition_raw, str) else None
            )
        except ValueError as error:
            raise ValueError(
                f"audit profile requirement {index} has an unsupported disposition"
            ) from error
        if disposition is None:
            raise ValueError(f"audit profile requirement {index} has an unsupported disposition")
        severity_raw = item["missing_severity"]
        try:
            severity = Severity(severity_raw) if isinstance(severity_raw, str) else None
        except ValueError as error:
            raise ValueError(
                f"audit profile requirement {index} has an unsupported missing_severity"
            ) from error
        if severity is None:
            raise ValueError(
                f"audit profile requirement {index} has an unsupported missing_severity"
            )
        requirements.append(
            EvidenceRequirement(
                capability_id=strings["capability"],
                title=strings["title"],
                category=strings["category"],
                methods=cast(tuple[str, ...], tuple(methods_raw)),
                disposition=disposition,
                severity=severity,
            )
        )

    return AuditProfile(
        profile_id=profile_id,
        profile_version=_profile_positive_integer(
            payload["profile_version"], name="audit profile profile_version"
        ),
        scope=scope,
        requirements=tuple(requirements),
    )


_BASE_REQUIREMENTS: tuple[tuple[str, str, str, tuple[str, ...], Severity], ...] = (
    (
        "signal_diagnostics",
        "Signal and label diagnostics",
        "statistical_validity",
        ("labels.*", "signal.*"),
        Severity.HIGH,
    ),
    (
        "temporal_validation",
        "Temporal cross-validation",
        "temporal_integrity",
        ("cv.*",),
        Severity.CRITICAL,
    ),
    (
        "resampling_inference",
        "Resampling and permutation inference",
        "statistical_validity",
        ("validation.bootstrap.*", "validation.permutation.*"),
        Severity.HIGH,
    ),
    (
        "advanced_inference",
        "Selection-aware advanced inference",
        "statistical_validity",
        (
            "validation.sharpe_inference",
            "validation.probability_of_backtest_overfitting",
            "validation.joint_stationary_bootstrap",
            "validation.white_reality_check",
            "validation.hansen_spa",
        ),
        Severity.HIGH,
    ),
    (
        "experiment_lineage",
        "Experiment and selection lineage",
        "experiment_integrity",
        ("experiment.*",),
        Severity.HIGH,
    ),
    (
        "multiple_testing",
        "Multiple-testing evidence",
        "experiment_integrity",
        ("validation.multiple_testing.*",),
        Severity.HIGH,
    ),
    (
        "parameter_robustness",
        "Parameter robustness",
        "robustness",
        ("validation.parameter_surface", "robustness.continuous_perturbation"),
        Severity.HIGH,
    ),
    (
        "temporal_robustness",
        "Subperiod robustness",
        "robustness",
        ("robustness.subperiod_analysis",),
        Severity.HIGH,
    ),
    (
        "universe_robustness",
        "Universe robustness",
        "robustness",
        ("robustness.universe_perturbation",),
        Severity.HIGH,
    ),
    (
        "regime_robustness",
        "Regime robustness",
        "robustness",
        ("regime.*",),
        Severity.HIGH,
    ),
    (
        "execution_realism",
        "Costs, liquidity, and capacity",
        "costs_capacity",
        ("costs.*",),
        Severity.HIGH,
    ),
    (
        "point_in_time_data",
        "Point-in-time data and revision controls",
        "data_integrity",
        (
            "bias.asof_join",
            "bias.future_data_check",
            "bias.revision_diagnostics",
            "bias.validate_dataset",
        ),
        Severity.CRITICAL,
    ),
    (
        "survivorship",
        "Survivorship and historical-universe controls",
        "temporal_integrity",
        (
            "bias.survivorship_diagnostics",
            "bias.membership_at",
            "bias.universe_drift",
        ),
        Severity.CRITICAL,
    ),
    (
        "adapter_provenance",
        "Vendor and backtester adapter provenance",
        "operational",
        ("adapters.*",),
        Severity.MEDIUM,
    ),
    (
        "plugin_provenance",
        "Explicit plugin activation provenance",
        "operational",
        ("plugins.*",),
        Severity.MEDIUM,
    ),
    (
        "options_evidence",
        "Options-extension evidence",
        "statistical_validity",
        ("options.*",),
        Severity.HIGH,
    ),
)


_DISPOSITIONS: Mapping[AuditScope, Mapping[str, EvidenceDisposition]] = MappingProxyType(
    {
        AuditScope.SIGNAL: MappingProxyType(
            {
                "signal_diagnostics": EvidenceDisposition.REQUIRED,
                "temporal_validation": EvidenceDisposition.REQUIRED,
                "resampling_inference": EvidenceDisposition.REQUIRED,
                "advanced_inference": EvidenceDisposition.OPTIONAL,
                "experiment_lineage": EvidenceDisposition.REQUIRED,
                "multiple_testing": EvidenceDisposition.REQUIRED,
                "parameter_robustness": EvidenceDisposition.REQUIRED,
                "temporal_robustness": EvidenceDisposition.REQUIRED,
                "universe_robustness": EvidenceDisposition.REQUIRED,
                "regime_robustness": EvidenceDisposition.REQUIRED,
                "execution_realism": EvidenceDisposition.NOT_APPLICABLE,
                "point_in_time_data": EvidenceDisposition.REQUIRED,
                "survivorship": EvidenceDisposition.REQUIRED,
                "adapter_provenance": EvidenceDisposition.OPTIONAL,
                "plugin_provenance": EvidenceDisposition.OPTIONAL,
                "options_evidence": EvidenceDisposition.NOT_APPLICABLE,
            }
        ),
        AuditScope.STRATEGY: MappingProxyType(
            {
                "signal_diagnostics": EvidenceDisposition.OPTIONAL,
                "temporal_validation": EvidenceDisposition.REQUIRED,
                "resampling_inference": EvidenceDisposition.REQUIRED,
                "advanced_inference": EvidenceDisposition.REQUIRED,
                "experiment_lineage": EvidenceDisposition.REQUIRED,
                "multiple_testing": EvidenceDisposition.REQUIRED,
                "parameter_robustness": EvidenceDisposition.REQUIRED,
                "temporal_robustness": EvidenceDisposition.REQUIRED,
                "universe_robustness": EvidenceDisposition.REQUIRED,
                "regime_robustness": EvidenceDisposition.REQUIRED,
                "execution_realism": EvidenceDisposition.REQUIRED,
                "point_in_time_data": EvidenceDisposition.REQUIRED,
                "survivorship": EvidenceDisposition.REQUIRED,
                "adapter_provenance": EvidenceDisposition.OPTIONAL,
                "plugin_provenance": EvidenceDisposition.OPTIONAL,
                "options_evidence": EvidenceDisposition.NOT_APPLICABLE,
            }
        ),
        AuditScope.OPTIONS: MappingProxyType(
            {
                "signal_diagnostics": EvidenceDisposition.OPTIONAL,
                "temporal_validation": EvidenceDisposition.REQUIRED,
                "resampling_inference": EvidenceDisposition.REQUIRED,
                "advanced_inference": EvidenceDisposition.REQUIRED,
                "experiment_lineage": EvidenceDisposition.REQUIRED,
                "multiple_testing": EvidenceDisposition.REQUIRED,
                "parameter_robustness": EvidenceDisposition.REQUIRED,
                "temporal_robustness": EvidenceDisposition.REQUIRED,
                "universe_robustness": EvidenceDisposition.OPTIONAL,
                "regime_robustness": EvidenceDisposition.OPTIONAL,
                "execution_realism": EvidenceDisposition.REQUIRED,
                "point_in_time_data": EvidenceDisposition.REQUIRED,
                "survivorship": EvidenceDisposition.OPTIONAL,
                "adapter_provenance": EvidenceDisposition.OPTIONAL,
                "plugin_provenance": EvidenceDisposition.OPTIONAL,
                "options_evidence": EvidenceDisposition.REQUIRED,
            }
        ),
    }
)


def standard_profile(scope: AuditScope | str = "strategy") -> AuditProfile:
    """Return the built-in standardized profile for one research scope."""

    try:
        selected_scope = AuditScope(scope)
    except ValueError as error:
        raise ValueError("scope must be 'signal', 'strategy', or 'options'") from error
    dispositions = _DISPOSITIONS[selected_scope]
    requirements = tuple(
        EvidenceRequirement(
            capability_id=capability_id,
            title=title,
            category=category,
            methods=methods,
            disposition=dispositions[capability_id],
            severity=severity,
        )
        for capability_id, title, category, methods, severity in _BASE_REQUIREMENTS
    )
    return AuditProfile(
        profile_id=f"standard.{selected_scope.value}",
        profile_version=1,
        scope=selected_scope,
        requirements=requirements,
    )


def _coverage_finding(
    requirement: EvidenceRequirement,
    source_names: tuple[str, ...],
) -> Finding:
    present = bool(source_names)
    if requirement.disposition == EvidenceDisposition.REQUIRED:
        state = FindingState.PASS if present else FindingState.UNKNOWN
        message = (
            "Recognized evidence is supplied for this required capability. This coverage pass does "
            "not certify the underlying research outcome."
            if present
            else "Required evidence for this profile capability was not supplied."
        )
    elif requirement.disposition == EvidenceDisposition.OPTIONAL:
        state = FindingState.PASS if present else FindingState.NOT_APPLICABLE
        message = (
            "Recognized optional evidence is supplied. This coverage pass does not certify the "
            "underlying research outcome."
            if present
            else (
                "This profile does not require the optional capability and no evidence was "
                "supplied."
            )
        )
    else:
        state = FindingState.WARN if present else FindingState.NOT_APPLICABLE
        message = (
            "Evidence was supplied for a capability declared not applicable to this scope; verify "
            "that the selected audit scope is correct."
            if present
            else "The selected profile declares this capability not applicable."
        )
    return Finding(
        code=f"EVIDENCE_{requirement.capability_id.upper()}",
        title=requirement.title,
        message=message,
        state=state,
        severity=requirement.severity,
        category=requirement.category,
        evidence={
            "capability": requirement.capability_id,
            "disposition": requirement.disposition.value,
            "accepted_methods": requirement.methods,
            "source_names": source_names,
            "coverage_only": True,
            "profile_rule_version": 1,
        },
    )


def _domain_finding(
    capability: EvidenceRequirement,
    source_name: str,
    result: AnalysisResult,
    finding: Finding,
    occurrence: int,
) -> Finding:
    identity = "\0".join((source_name, finding.code, str(occurrence))).encode()
    suffix = hashlib.sha256(identity).hexdigest()[:16].upper()
    return Finding(
        code=f"DOMAIN_{capability.capability_id.upper()}_{suffix}",
        title=finding.title,
        message=finding.message,
        state=finding.state,
        severity=finding.severity,
        category=finding.category,
        evidence={
            "profile_capability": capability.capability_id,
            "source_name": source_name,
            "source_method": result.metadata.method,
            "source_method_version": result.metadata.method_version,
            "source_finding_code": finding.code,
            "source_category": finding.category,
            "source_evidence": finding.evidence,
            "propagated_without_reinterpretation": True,
        },
    )


def _sort_findings(findings: list[Finding]) -> tuple[Finding, ...]:
    state_order = {
        FindingState.FAIL: 0,
        FindingState.WARN: 1,
        FindingState.UNKNOWN: 2,
        FindingState.PASS: 3,
        FindingState.NOT_APPLICABLE: 4,
    }
    severity_order = {
        Severity.CRITICAL: 0,
        Severity.HIGH: 1,
        Severity.MEDIUM: 2,
        Severity.LOW: 3,
        Severity.INFO: 4,
    }
    return tuple(
        sorted(
            findings,
            key=lambda item: (
                item.category,
                state_order[item.state],
                severity_order[item.severity],
                item.code,
            ),
        )
    )


def _category_coverage(
    requirements: tuple[EvidenceRequirement, ...],
    matched: Mapping[str, tuple[str, ...]],
) -> tuple[JsonValue, ...]:
    categories: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "required": 0,
            "required_present": 0,
            "optional": 0,
            "optional_present": 0,
            "not_applicable": 0,
            "not_applicable_present": 0,
        }
    )
    for requirement in requirements:
        row = categories[requirement.category]
        disposition = requirement.disposition.value
        row[disposition] += 1
        if matched[requirement.capability_id]:
            row[f"{disposition}_present"] += 1
    rows: list[JsonValue] = []
    for category in sorted(categories):
        values = categories[category]
        required = values["required"]
        rows.append(
            {
                "category": category,
                **values,
                "required_coverage": (values["required_present"] / required if required else None),
            }
        )
    return tuple(rows)


def run_standard_audit(
    context: AuditContext,
    *,
    scope: AuditScope | str = "strategy",
    profile: AuditProfile | None = None,
) -> AnalysisResult:
    """Assemble a categorical cross-phase audit without a universal quality score."""

    if not isinstance(context, AuditContext):
        raise TypeError("context must be an AuditContext")
    selected_scope = AuditScope(scope)
    selected_profile = standard_profile(selected_scope) if profile is None else profile
    if not isinstance(selected_profile, AuditProfile):
        raise TypeError("profile must be an AuditProfile")
    if selected_profile.scope != selected_scope:
        raise ValueError("profile scope does not match the requested audit scope")
    declared_scope = context.policies.get("study_type")
    if declared_scope is not None and declared_scope != selected_scope.value:
        raise ValueError("context study_type policy does not match the requested audit scope")

    matched_lists: dict[str, list[str]] = {
        requirement.capability_id: [] for requirement in selected_profile.requirements
    }
    assignment: dict[str, EvidenceRequirement] = {}
    unrecognized: list[str] = []
    for source_name, result in sorted(context.results.items()):
        matches = [
            requirement
            for requirement in selected_profile.requirements
            if requirement.matches(result.metadata.method)
        ]
        if len(matches) > 1:
            capabilities = ", ".join(item.capability_id for item in matches)
            raise ValueError(
                f"evidence {source_name!r} method {result.metadata.method!r} matches multiple "
                f"profile capabilities: {capabilities}"
            )
        if not matches:
            unrecognized.append(source_name)
            continue
        requirement = matches[0]
        matched_lists[requirement.capability_id].append(source_name)
        assignment[source_name] = requirement
    matched = {name: tuple(values) for name, values in matched_lists.items()}

    findings = [
        _coverage_finding(requirement, matched[requirement.capability_id])
        for requirement in selected_profile.requirements
    ]
    domain_rows: list[JsonValue] = []
    for source_name, requirement in sorted(assignment.items()):
        result = context.results[source_name]
        occurrences: Counter[str] = Counter()
        for source_finding in result.findings:
            occurrence = occurrences[source_finding.code]
            occurrences[source_finding.code] += 1
            findings.append(
                _domain_finding(
                    requirement,
                    source_name,
                    result,
                    source_finding,
                    occurrence,
                )
            )
            domain_rows.append(
                {
                    "capability": requirement.capability_id,
                    "source_name": source_name,
                    "source_method": result.metadata.method,
                    "source_method_version": result.metadata.method_version,
                    "code": source_finding.code,
                    "state": source_finding.state.value,
                    "severity": source_finding.severity.value,
                    "category": source_finding.category,
                    "title": source_finding.title,
                    "message": source_finding.message,
                    "evidence": source_finding.evidence,
                }
            )
    if unrecognized:
        findings.append(
            Finding(
                code="UNRECOGNIZED_EVIDENCE",
                title="Evidence methods are outside the selected profile",
                message=(
                    "One or more supplied results are retained in the inventory but are not used "
                    "to satisfy a profile capability."
                ),
                state=FindingState.WARN,
                severity=Severity.HIGH,
                category="operational",
                evidence={"source_names": tuple(unrecognized), "profile_rule_version": 1},
            )
        )

    normalized_findings = _sort_findings(findings)
    counts = Counter(finding.state for finding in normalized_findings)
    required = tuple(
        requirement
        for requirement in selected_profile.requirements
        if requirement.disposition == EvidenceDisposition.REQUIRED
    )
    optional = tuple(
        requirement
        for requirement in selected_profile.requirements
        if requirement.disposition == EvidenceDisposition.OPTIONAL
    )
    required_present = sum(bool(matched[item.capability_id]) for item in required)
    optional_present = sum(bool(matched[item.capability_id]) for item in optional)

    requirement_rows: tuple[JsonValue, ...] = tuple(
        {
            "capability": requirement.capability_id,
            "title": requirement.title,
            "category": requirement.category,
            "disposition": requirement.disposition.value,
            "accepted_methods": requirement.methods,
            "present": bool(matched[requirement.capability_id]),
            "source_names": matched[requirement.capability_id],
        }
        for requirement in selected_profile.requirements
    )
    inventory_rows: tuple[JsonValue, ...] = tuple(
        {
            "source_name": source_name,
            "method": result.metadata.method,
            "method_version": result.metadata.method_version,
            "schema_version": result.schema_version,
            "capability": (
                assignment[source_name].capability_id if source_name in assignment else None
            ),
            "disposition": (
                assignment[source_name].disposition.value if source_name in assignment else None
            ),
            "recognized": source_name in assignment,
            "finding_count": len(result.findings),
            "warning_count": len(result.warnings),
            "has_seed": result.metadata.seed is not None,
            "has_input_fingerprint": result.metadata.input_fingerprint is not None,
        }
        for source_name, result in sorted(context.results.items())
    )
    required_coverage = required_present / len(required) if required else 1.0
    optional_coverage = optional_present / len(optional) if optional else 1.0
    if not isfinite(required_coverage) or not isfinite(optional_coverage):  # pragma: no cover
        raise RuntimeError("audit profile coverage must be finite")
    result_methods = {
        source_name: result.metadata.method for source_name, result in context.results.items()
    }
    return AnalysisResult(
        metadata=ResultMetadata(
            method="audit.standard",
            method_version=1,
            parameters={
                "profile_id": selected_profile.profile_id,
                "profile_version": selected_profile.profile_version,
                "profile_schema_version": "1",
                "scope": selected_profile.scope.value,
                "score_model": None,
                "coverage_rule_version": 1,
                "domain_findings": "propagated_without_reinterpretation",
                "result_methods": result_methods,
                "policies": context.policies,
            },
        ),
        metrics={
            "evidence_coverage": required_coverage,
            "required_evidence_coverage": required_coverage,
            "optional_evidence_coverage": optional_coverage,
            "required_capability_count": len(required),
            "required_capability_present_count": required_present,
            "required_evidence_complete": required_present == len(required),
            "optional_capability_count": len(optional),
            "optional_capability_present_count": optional_present,
            "supplied_result_count": len(context.results),
            "recognized_result_count": len(assignment),
            "unrecognized_result_count": len(unrecognized),
            "finding_count": len(normalized_findings),
            "failure_count": counts[FindingState.FAIL],
            "warning_count": counts[FindingState.WARN],
            "unknown_count": counts[FindingState.UNKNOWN],
            "not_applicable_count": counts[FindingState.NOT_APPLICABLE],
            "domain_finding_count": len(domain_rows),
        },
        findings=normalized_findings,
        tables={
            "category_coverage": _category_coverage(selected_profile.requirements, matched),
            "evidence_requirements": requirement_rows,
            "evidence_inventory": inventory_rows,
            "domain_findings": tuple(domain_rows),
        },
        warnings=(
            "The standardized profile computes evidence coverage, not a universal strategy-quality "
            "or profitability score.",
            "Coverage PASS findings mean recognized evidence was supplied; domain findings retain "
            "their original state, severity, thresholds, and method semantics.",
        ),
    )


def standard_audit(
    *,
    results: Mapping[str, AnalysisResult] | None = None,
    policies: Mapping[str, JsonValue] | None = None,
    scope: AuditScope | str = "strategy",
    profile: AuditProfile | None = None,
) -> AuditReport:
    """Run a versioned cross-phase profile and return a renderable report."""

    context = AuditContext(results=results or {}, policies=policies or {})
    return AuditReport(run_standard_audit(context, scope=scope, profile=profile))


__all__ = [
    "AuditProfile",
    "AuditScope",
    "EvidenceDisposition",
    "EvidenceRequirement",
    "run_standard_audit",
    "standard_audit",
    "standard_profile",
]
