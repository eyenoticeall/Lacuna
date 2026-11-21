"""Deterministic audit rules over structured Lacuna evidence."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from math import isfinite
from types import MappingProxyType
from typing import TYPE_CHECKING, Protocol, cast

from lacuna.types import (
    AnalysisResult,
    Finding,
    FindingState,
    JsonValue,
    ResultMetadata,
    Severity,
    _freeze_mapping,
)

if TYPE_CHECKING:
    from lacuna.report import AuditReport


class ApplicabilityState(StrEnum):
    """Whether a rule can be evaluated from the supplied context."""

    APPLICABLE = "APPLICABLE"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True, slots=True)
class Applicability:
    """A rule's pre-computation applicability decision."""

    state: ApplicabilityState
    reason: str


@dataclass(frozen=True, slots=True)
class AuditContext:
    """Read-only named evidence and declared policies supplied to audit rules."""

    results: Mapping[str, AnalysisResult] = field(default_factory=dict)
    policies: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if any(not name for name in self.results):
            raise ValueError("audit result names must not be empty")
        if any(not name for name in self.policies):
            raise ValueError("audit policy names must not be empty")
        if any(not isinstance(result, AnalysisResult) for result in self.results.values()):
            raise TypeError("audit context results must contain AnalysisResult values")
        object.__setattr__(self, "results", MappingProxyType(dict(self.results)))
        object.__setattr__(self, "policies", _freeze_mapping(self.policies))


class AuditRule(Protocol):
    """Protocol for deterministic, independently executable audit rules."""

    @property
    def rule_id(self) -> str: ...

    @property
    def rule_version(self) -> int: ...

    @property
    def title(self) -> str: ...

    @property
    def category(self) -> str: ...

    @property
    def severity(self) -> Severity: ...

    @property
    def weight(self) -> float: ...

    def applicable(self, context: AuditContext) -> Applicability: ...

    def evaluate(self, context: AuditContext) -> Finding: ...


@dataclass(frozen=True, slots=True)
class _ResultRule:
    rule_id: str
    title: str
    result_name: str
    category: str
    severity: Severity
    weight: float
    rule_version: int = 1

    def applicable(self, context: AuditContext) -> Applicability:
        if self.result_name not in context.results:
            return Applicability(
                ApplicabilityState.UNKNOWN,
                f"required {self.result_name!r} analysis evidence was not supplied",
            )
        return Applicability(ApplicabilityState.APPLICABLE, "required evidence is available")

    def _finding(
        self,
        *,
        state: FindingState,
        message: str,
        evidence: Mapping[str, JsonValue] = MappingProxyType({}),
    ) -> Finding:
        return Finding(
            code=self.rule_id,
            title=self.title,
            message=message,
            state=state,
            severity=self.severity,
            category=self.category,
            evidence={
                "rule_version": self.rule_version,
                "weight": self.weight,
                **evidence,
            },
        )


_UNRESOLVED_HORIZON_MESSAGE = (
    "Multi-horizon IC evidence requires an inference_horizon policy that selects exactly one "
    "horizon summary."
)


def _inference_ic_summary(
    result: AnalysisResult,
    context: AuditContext,
) -> tuple[Mapping[str, JsonValue] | None, JsonValue]:
    """Return the IC summary for the declared inference horizon.

    Pooled IC metrics mix horizons whenever labels carry more than one, so a
    per-horizon summary table takes precedence. Evidence without a horizon
    table is a single IC series and keeps its top-level metrics.
    """

    declared = context.policies.get("inference_horizon")
    table = result.tables.get("ic_overall_by_horizon", result.tables.get("ic_by_horizon"))
    if not isinstance(table, tuple) or not table:
        return result.metrics, declared
    rows = tuple(row for row in table if isinstance(row, Mapping) and "horizon" in row)
    if len(rows) != len(table):
        return None, declared
    horizons = {row["horizon"] for row in rows}
    if declared is None and len(horizons) == 1:
        return rows[0], rows[0]["horizon"]
    matching = tuple(row for row in rows if row["horizon"] == declared)
    if len(matching) != 1:
        return None, declared
    return matching[0], declared


class _IcDefinedRule(_ResultRule):
    def evaluate(self, context: AuditContext) -> Finding:
        result = context.results[self.result_name]
        summary, horizon = _inference_ic_summary(result, context)
        if summary is None:
            return self._finding(
                state=FindingState.UNKNOWN,
                message=_UNRESOLVED_HORIZON_MESSAGE,
                evidence={"inference_horizon": horizon},
            )
        value = summary.get("mean_ic")
        if isinstance(value, bool) or not isinstance(value, int | float):
            return self._finding(
                state=FindingState.FAIL,
                message="No defined IC periods remain after sample and variance checks.",
                evidence={"mean_ic": None, "inference_horizon": horizon},
            )
        return self._finding(
            state=FindingState.PASS,
            message="The IC time series contains a defined aggregate correlation.",
            evidence={"mean_ic": value, "inference_horizon": horizon},
        )


class _IcSupportRule(_ResultRule):
    pass_threshold = 60
    warn_threshold = 20

    def evaluate(self, context: AuditContext) -> Finding:
        result = context.results[self.result_name]
        summary, horizon = _inference_ic_summary(result, context)
        if summary is None:
            return self._finding(
                state=FindingState.UNKNOWN,
                message=_UNRESOLVED_HORIZON_MESSAGE,
                evidence={"inference_horizon": horizon},
            )
        raw = summary.get("n_periods")
        count = int(raw) if isinstance(raw, int | float) and not isinstance(raw, bool) else 0
        if count >= self.pass_threshold:
            state = FindingState.PASS
            message = "IC is supported by at least 60 defined periods."
        elif count >= self.warn_threshold:
            state = FindingState.WARN
            message = (
                "IC has moderate period support; dependence-aware uncertainty remains important."
            )
        else:
            state = FindingState.FAIL
            message = "Fewer than 20 defined periods provide weak support for aggregate IC."
        return self._finding(
            state=state,
            message=message,
            evidence={
                "n_periods": count,
                "warn_threshold": self.warn_threshold,
                "pass_threshold": self.pass_threshold,
                "inference_horizon": horizon,
            },
        )


_UNRESOLVED_MONOTONICITY_MESSAGE = (
    "Multi-horizon quantile evidence requires an inference_horizon policy that selects exactly "
    "one horizon's monotonicity."
)


def _inference_monotonicity(
    result: AnalysisResult,
    context: AuditContext,
) -> tuple[bool, JsonValue, JsonValue]:
    """Return the quantile monotonicity for the declared inference horizon.

    The top-level metric describes one headline horizon, which need not be the horizon the
    audit infers on, so the per-horizon table decides whenever it can. Evidence without a
    horizon is a single series and keeps its top-level metric.
    """

    declared = context.policies.get("inference_horizon")
    headline = result.metrics.get("spearman_monotonicity")
    table = result.tables.get("monotonicity")
    rows = (
        tuple(row for row in table if isinstance(row, Mapping) and "horizon" in row)
        if isinstance(table, tuple)
        else ()
    )
    if not rows:
        return True, headline, declared
    horizons = {row["horizon"] for row in rows}
    if declared is None:
        if len(horizons) == 1:
            return True, headline, next(iter(horizons))
        return False, None, declared
    if result.metadata.parameters.get("headline_horizon") == declared:
        return True, headline, declared
    matching = tuple(row for row in rows if row["horizon"] == declared)
    if len(matching) != 1:
        return False, None, declared
    return True, matching[0].get("spearman_monotonicity"), declared


class _MonotonicityRule(_ResultRule):
    pass_threshold = 0.7
    warn_threshold = 0.4

    def evaluate(self, context: AuditContext) -> Finding:
        result = context.results[self.result_name]
        resolved, raw, horizon = _inference_monotonicity(result, context)
        if not resolved:
            return self._finding(
                state=FindingState.UNKNOWN,
                message=_UNRESOLVED_MONOTONICITY_MESSAGE,
                evidence={"inference_horizon": horizon},
            )
        if isinstance(raw, bool) or not isinstance(raw, int | float):
            return self._finding(
                state=FindingState.UNKNOWN,
                message="Quantile monotonicity could not be computed from the supplied groups.",
                evidence={"inference_horizon": horizon},
            )
        value = float(raw)
        if value >= self.pass_threshold:
            state = FindingState.PASS
            message = "Average quantile returns are strongly ordered with signal rank."
        elif value >= self.warn_threshold:
            state = FindingState.WARN
            message = "Average quantile returns have only moderate rank ordering."
        else:
            state = FindingState.FAIL
            message = "Average quantile returns are weakly or inversely ordered."
        return self._finding(
            state=state,
            message=message,
            evidence={
                "spearman_monotonicity": value,
                "warn_threshold": self.warn_threshold,
                "pass_threshold": self.pass_threshold,
                "inference_horizon": horizon,
            },
        )


class _TurnoverMeasuredRule(_ResultRule):
    def evaluate(self, context: AuditContext) -> Finding:
        result = context.results[self.result_name]
        value = result.metrics.get("mean_rank_turnover")
        if not isinstance(value, int | float):
            return self._finding(
                state=FindingState.UNKNOWN,
                message="Rank turnover could not be estimated from consecutive observations.",
            )
        return self._finding(
            state=FindingState.PASS,
            message="Rank turnover is measured and available for execution review.",
            evidence={"mean_rank_turnover": float(value)},
        )


class _DecayCoverageRule(_ResultRule):
    def evaluate(self, context: AuditContext) -> Finding:
        result = context.results[self.result_name]
        rows = result.tables.get("ic_decay")
        if (
            not isinstance(rows, tuple)
            or not rows
            or any(
                not isinstance(row, Mapping) or "horizon" not in row or "mean_ic" not in row
                for row in rows
            )
        ):
            return self._finding(
                state=FindingState.UNKNOWN,
                message="Per-horizon decay evidence with defined IC status was not supplied.",
            )
        horizon_rows = cast(tuple[Mapping[str, JsonValue], ...], rows)
        undefined = tuple(
            str(row["horizon"])
            for row in horizon_rows
            if isinstance(row["mean_ic"], bool) or not isinstance(row["mean_ic"], int | float)
        )
        count = len(horizon_rows) - len(undefined)
        if count >= 3:
            state = FindingState.PASS
            message = "Signal decay is evaluated across at least three horizons with defined IC."
        elif count >= 2:
            state = FindingState.WARN
            message = (
                "Signal decay is visible, but only two horizons with defined IC limit shape "
                "interpretation."
            )
        else:
            state = FindingState.FAIL
            message = "Fewer than two horizons have defined IC, so decay cannot be established."
        return self._finding(
            state=state,
            message=message,
            evidence={
                "n_horizons": len(horizon_rows),
                "n_defined_horizons": count,
                "undefined_horizons": undefined,
            },
        )


class _BootstrapRule(_ResultRule):
    minimum_sample = 30

    def evaluate(self, context: AuditContext) -> Finding:
        result = context.results[self.result_name]
        lower = result.metrics.get("confidence_lower")
        upper = result.metrics.get("confidence_upper")
        observed = result.metrics.get("observed")
        sample = result.metrics.get("n_raw")
        if not (
            isinstance(lower, int | float)
            and isinstance(upper, int | float)
            and isinstance(observed, int | float)
        ):
            return self._finding(
                state=FindingState.UNKNOWN,
                message="Bootstrap confidence bounds are unavailable.",
            )
        if isinstance(sample, bool) or not isinstance(sample, int):
            return self._finding(
                state=FindingState.UNKNOWN,
                message="The number of resampled periods behind the interval is unavailable.",
            )
        lower_value = float(lower)
        upper_value = float(upper)
        observed_value = float(observed)
        if sample < self.minimum_sample:
            state = FindingState.WARN
            message = (
                f"Fewer than {self.minimum_sample} periods were resampled, so the interval is too "
                "imprecise to support or reject the mean IC."
            )
        elif lower_value > 0.0:
            state = FindingState.PASS
            message = "The bootstrap confidence interval is strictly positive."
        elif upper_value < 0.0:
            state = FindingState.FAIL
            message = "The bootstrap confidence interval is strictly negative."
        else:
            state = FindingState.WARN
            message = "The bootstrap confidence interval includes zero."
        return self._finding(
            state=state,
            message=message,
            evidence={
                "observed": observed_value,
                "confidence_lower": lower_value,
                "confidence_upper": upper_value,
                "n_resampled": sample,
                "minimum_sample": self.minimum_sample,
                "inference_horizon": context.policies.get("inference_horizon"),
                "sampling": context.policies.get("ic_inference_sampling"),
            },
        )


class _LabelIntervalsRule(_ResultRule):
    def evaluate(self, context: AuditContext) -> Finding:
        result = context.results[self.result_name]
        if result.metadata.method != "labels.forward_returns":
            return self._finding(
                state=FindingState.UNKNOWN,
                message="The supplied label evidence is not a forward-return label result.",
                evidence={"method": result.metadata.method},
            )
        count = result.metrics.get("n_labels")
        return self._finding(
            state=FindingState.PASS,
            message="Forward labels include explicit sample, entry, and exit timing.",
            evidence={"n_labels": count},
        )


class _PriceAdjustmentRule(_ResultRule):
    def evaluate(self, context: AuditContext) -> Finding:
        result = context.results[self.result_name]
        unknown = any(finding.code == "PRICE_ADJUSTMENT_UNKNOWN" for finding in result.findings)
        if unknown:
            return self._finding(
                state=FindingState.UNKNOWN,
                message="Price adjustment semantics were not declared for forward labels.",
            )
        adjustment = result.metadata.parameters.get("price_adjustment")
        return self._finding(
            state=FindingState.PASS,
            message="Price adjustment semantics are explicitly declared.",
            evidence={"price_adjustment": adjustment},
        )


class _DelistingRule(_ResultRule):
    def evaluate(self, context: AuditContext) -> Finding:
        result = context.results[self.result_name]
        unknown = any(finding.code == "DELISTING_RETURNS_UNKNOWN" for finding in result.findings)
        if unknown:
            return self._finding(
                state=FindingState.UNKNOWN,
                message="Delisting-return handling was not supplied.",
            )
        return self._finding(
            state=FindingState.PASS,
            message="Delisting-return handling is represented in label construction.",
        )


_PURGED_SPLIT_METHODS = frozenset({"cv.purged_kfold", "cv.combinatorial_purged_kfold"})
_OBSERVATION_HORIZON = re.compile(r"(?P<count>[1-9][0-9]*)D")


def _split_count(result: AnalysisResult, name: str) -> int | None:
    value = result.metrics.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


class _PurgedValidationRule(_ResultRule):
    """Check that supplied split evidence purged against overlapping label intervals.

    Split evidence carries no input fingerprint, so the rule cannot prove the split was
    built from the audited study's labels. It can flag an inconsistency: consecutive labels
    spanning two or more observations overlap the first test observation after their start,
    so a purged split of them removes at least one observation. Zero purged observations
    is still legitimate for a split built on non-overlapping sampled labels (for example
    every fifth observation of a five-observation horizon), which the rule cannot tell
    apart, so the outcome is a warning rather than a failure.
    """

    def evaluate(self, context: AuditContext) -> Finding:
        result = context.results[self.result_name]
        method = result.metadata.method
        if method not in _PURGED_SPLIT_METHODS:
            return self._finding(
                state=FindingState.UNKNOWN,
                message="The supplied split evidence does not establish purged validation.",
                evidence={"method": method},
            )
        purged = _split_count(result, "purged_observations")
        embargoed = _split_count(result, "embargoed_observations")
        evidence: dict[str, JsonValue] = {
            "method": method,
            "purged_observations": purged,
            "embargoed_observations": embargoed,
            "data_identity_verified": False,
        }
        if purged is None:
            return self._finding(
                state=FindingState.UNKNOWN,
                message="The supplied split evidence does not report its purged observations.",
                evidence=evidence,
            )
        horizon = context.policies.get("inference_horizon")
        match = _OBSERVATION_HORIZON.fullmatch(horizon) if isinstance(horizon, str) else None
        if match is not None and int(match.group("count")) >= 2 and purged == 0:
            return self._finding(
                state=FindingState.WARN,
                message=(
                    "The supplied split purged no observations although the inference "
                    "horizon's labels span several observations. Consecutive labels of that "
                    "horizon overlap a test boundary, so unless the split was built on "
                    "non-overlapping sampled labels it was not purged against the audited "
                    "labels."
                ),
                evidence={**evidence, "inference_horizon": horizon},
            )
        return self._finding(
            state=FindingState.PASS,
            message=(
                "A supplied validation split applied interval-aware purging. The split "
                "evidence does not identify its input, so this does not verify that it was "
                "built from the audited labels."
            ),
            evidence=evidence,
        )


@dataclass(frozen=True, slots=True)
class _PolicyRule:
    rule_id: str
    title: str
    policy_name: str
    missing_message: str
    category: str
    severity: Severity
    weight: float
    not_applicable_for_signal_study: bool = False
    rule_version: int = 1

    def applicable(self, context: AuditContext) -> Applicability:
        if self.not_applicable_for_signal_study and context.policies.get("study_type") == "signal":
            return Applicability(
                ApplicabilityState.NOT_APPLICABLE,
                "the check requires trades or a portfolio simulation, not a signal-only study",
            )
        if self.policy_name not in context.policies:
            return Applicability(ApplicabilityState.UNKNOWN, self.missing_message)
        return Applicability(ApplicabilityState.APPLICABLE, "declared policy is available")

    def evaluate(self, context: AuditContext) -> Finding:
        value = context.policies[self.policy_name]
        state = FindingState.PASS if value is True else FindingState.WARN
        return Finding(
            code=self.rule_id,
            title=self.title,
            message=(
                "The required policy is explicitly supported."
                if value is True
                else "The supplied policy does not confirm this safeguard."
            ),
            state=state,
            severity=self.severity,
            category=self.category,
            evidence={
                "rule_version": self.rule_version,
                "weight": self.weight,
                "policy": self.policy_name,
                "value": value,
            },
        )


def default_rules() -> tuple[AuditRule, ...]:
    """Return the ordered, versioned v0.1 audit rule set."""

    return (
        _IcDefinedRule(
            "IC_DEFINED",
            "Information coefficient is defined",
            "ic",
            "statistical_validity",
            Severity.HIGH,
            12.0,
            rule_version=2,
        ),
        _IcSupportRule(
            "IC_PERIOD_SUPPORT",
            "Information coefficient has period support",
            "ic",
            "statistical_validity",
            Severity.HIGH,
            12.0,
            rule_version=2,
        ),
        _MonotonicityRule(
            "QUANTILE_MONOTONICITY",
            "Quantile returns are monotonic",
            "quantiles",
            "statistical_validity",
            Severity.MEDIUM,
            10.0,
            rule_version=2,
        ),
        _BootstrapRule(
            "BOOTSTRAP_INTERVAL",
            "Bootstrap interval supports the mean IC",
            "bootstrap",
            "statistical_validity",
            Severity.HIGH,
            12.0,
            rule_version=2,
        ),
        _DecayCoverageRule(
            "HORIZON_DECAY_COVERAGE",
            "Signal decay covers multiple horizons",
            "decay",
            "robustness",
            Severity.MEDIUM,
            10.0,
            rule_version=2,
        ),
        _LabelIntervalsRule(
            "LABEL_INTERVALS_PRESENT",
            "Forward labels expose earning intervals",
            "labels",
            "temporal_integrity",
            Severity.CRITICAL,
            10.0,
        ),
        _PurgedValidationRule(
            "PURGED_VALIDATION_SUPPLIED",
            "Validation applies interval purging",
            "split",
            "temporal_integrity",
            Severity.HIGH,
            10.0,
            rule_version=2,
        ),
        _PriceAdjustmentRule(
            "PRICE_ADJUSTMENT_DECLARED",
            "Price adjustment semantics are declared",
            "labels",
            "data_integrity",
            Severity.HIGH,
            8.0,
        ),
        _DelistingRule(
            "DELISTING_HANDLING_DECLARED",
            "Delisting handling is declared",
            "labels",
            "data_integrity",
            Severity.HIGH,
            8.0,
        ),
        _TurnoverMeasuredRule(
            "TURNOVER_MEASURED",
            "Signal turnover is measured",
            "turnover",
            "costs_capacity",
            Severity.MEDIUM,
            4.0,
        ),
        _PolicyRule(
            "SURVIVORSHIP_HANDLING_DECLARED",
            "Survivorship handling is declared",
            "survivorship_safe",
            "historical-universe or survivorship evidence was not supplied",
            "temporal_integrity",
            Severity.HIGH,
            2.0,
        ),
        _PolicyRule(
            "TRIAL_HISTORY_AVAILABLE",
            "Research trial history is available",
            "trial_history_available",
            "experiment trial history was not supplied",
            "experiment_integrity",
            Severity.HIGH,
            2.0,
        ),
        _PolicyRule(
            "TRANSACTION_COST_EVIDENCE",
            "Transaction-cost evidence is available",
            "transaction_costs_available",
            "transaction-cost evidence was not supplied",
            "costs_capacity",
            Severity.HIGH,
            4.0,
            not_applicable_for_signal_study=True,
        ),
    )


def _unavailable_finding(rule: AuditRule, applicability: Applicability) -> Finding:
    state = (
        FindingState.UNKNOWN
        if applicability.state == ApplicabilityState.UNKNOWN
        else FindingState.NOT_APPLICABLE
    )
    return Finding(
        code=rule.rule_id,
        title=rule.title,
        message=applicability.reason,
        state=state,
        severity=rule.severity,
        category=rule.category,
        evidence={"rule_version": rule.rule_version, "weight": rule.weight},
    )


_STATE_ORDER = {
    FindingState.FAIL: 0,
    FindingState.WARN: 1,
    FindingState.UNKNOWN: 2,
    FindingState.PASS: 3,
    FindingState.NOT_APPLICABLE: 4,
}
_SEVERITY_ORDER = {
    Severity.CRITICAL: 0,
    Severity.HIGH: 1,
    Severity.MEDIUM: 2,
    Severity.LOW: 3,
    Severity.INFO: 4,
}


def _score(
    findings: Sequence[Finding],
    rule_weights: Mapping[str, float],
) -> tuple[dict[str, JsonValue], tuple[JsonValue, ...]]:
    credits = {
        FindingState.PASS: 1.0,
        FindingState.WARN: 0.5,
        FindingState.FAIL: 0.0,
        FindingState.UNKNOWN: 0.0,
    }
    by_category: dict[str, dict[str, float]] = defaultdict(
        lambda: {"earned": 0.0, "possible": 0.0, "unknown": 0.0}
    )
    assessed_weight = 0.0
    applicable_weight = 0.0
    for finding in findings:
        if finding.state == FindingState.NOT_APPLICABLE:
            continue
        weight = rule_weights[finding.code]
        component = by_category[finding.category]
        component["possible"] += weight
        applicable_weight += weight
        if finding.state == FindingState.UNKNOWN:
            component["unknown"] += weight
        else:
            assessed_weight += weight
        component["earned"] += weight * credits[finding.state]
    earned = sum(component["earned"] for component in by_category.values())
    possible = sum(component["possible"] for component in by_category.values())
    score = 100.0 * earned / possible if possible else 0.0
    coverage = assessed_weight / applicable_weight if applicable_weight else 1.0
    rows: list[JsonValue] = []
    for category_name in sorted(by_category):
        component = by_category[category_name]
        rows.append(
            {
                "category": category_name,
                "earned_weight": component["earned"],
                "possible_weight": component["possible"],
                "unknown_weight": component["unknown"],
                "score": (
                    100.0 * component["earned"] / component["possible"]
                    if component["possible"]
                    else None
                ),
            }
        )
    return (
        {
            "robustness_score": score,
            "evidence_coverage": coverage,
            "earned_weight": earned,
            "possible_weight": possible,
            "unknown_weight": sum(component["unknown"] for component in by_category.values()),
        },
        tuple(rows),
    )


def run_audit(
    context: AuditContext,
    *,
    rules: Sequence[AuditRule] | None = None,
) -> AnalysisResult:
    """Evaluate rules, explicit missing evidence, and the versioned v0.1 score."""

    selected_rules = tuple(default_rules() if rules is None else rules)
    rule_ids = [rule.rule_id for rule in selected_rules]
    if any(not rule_id for rule_id in rule_ids):
        raise ValueError("audit rule identifiers must not be empty")
    if len(rule_ids) != len(set(rule_ids)):
        raise ValueError("audit rule identifiers must be unique")
    for rule in selected_rules:
        if rule.rule_version < 1:
            raise ValueError(f"audit rule {rule.rule_id!r} has an invalid version")
        if not rule.title or not rule.category:
            raise ValueError(f"audit rule {rule.rule_id!r} has empty descriptive metadata")
        if not isfinite(rule.weight) or rule.weight <= 0.0:
            raise ValueError(f"audit rule {rule.rule_id!r} weight must be positive and finite")
    findings: list[Finding] = []
    for rule in selected_rules:
        applicability = rule.applicable(context)
        if applicability.state == ApplicabilityState.APPLICABLE:
            finding = rule.evaluate(context)
            if finding.code != rule.rule_id:
                raise ValueError(
                    f"audit rule {rule.rule_id!r} returned finding code {finding.code!r}"
                )
            if finding.category != rule.category or finding.severity != rule.severity:
                raise ValueError(
                    f"audit rule {rule.rule_id!r} returned inconsistent category or severity"
                )
        else:
            finding = _unavailable_finding(rule, applicability)
        findings.append(finding)
    findings.sort(
        key=lambda finding: (
            finding.category,
            _STATE_ORDER[finding.state],
            _SEVERITY_ORDER[finding.severity],
            finding.code,
        )
    )
    weights = {rule.rule_id: rule.weight for rule in selected_rules}
    score_metrics, score_rows = _score(findings, weights)
    counts = Counter(finding.state.value for finding in findings)
    finding_summary = tuple(
        {"state": state.value, "count": counts.get(state.value, 0)} for state in FindingState
    )
    return AnalysisResult(
        metadata=ResultMetadata(
            method="audit.v0_1",
            method_version=1,
            parameters={
                "score_version": 1,
                "unknown_credit": 0.0,
                "warn_credit": 0.5,
                "not_applicable_policy": "excluded",
                "rule_versions": {rule.rule_id: rule.rule_version for rule in selected_rules},
                "result_methods": {
                    name: result.metadata.method for name, result in context.results.items()
                },
            },
        ),
        metrics={
            **score_metrics,
            "finding_count": len(findings),
            "failure_count": counts.get(FindingState.FAIL.value, 0),
            "warning_count": counts.get(FindingState.WARN.value, 0),
            "unknown_count": counts.get(FindingState.UNKNOWN.value, 0),
            "not_applicable_count": counts.get(FindingState.NOT_APPLICABLE.value, 0),
        },
        findings=tuple(findings),
        tables={
            "score_components": score_rows,
            "finding_summary": finding_summary,
        },
    )


def audit(
    *,
    results: Mapping[str, AnalysisResult] | None = None,
    policies: Mapping[str, JsonValue] | None = None,
    rules: Sequence[AuditRule] | None = None,
) -> AuditReport:
    """Run the audit and return a renderable report."""

    from lacuna.report import AuditReport

    context = AuditContext(results=results or {}, policies=policies or {})
    return AuditReport(run_audit(context, rules=rules))


__all__ = [
    "Applicability",
    "ApplicabilityState",
    "AuditContext",
    "AuditRule",
    "audit",
    "default_rules",
    "run_audit",
]
