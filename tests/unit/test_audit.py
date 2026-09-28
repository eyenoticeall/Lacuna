from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import polars as pl
import pytest

from lacuna.audit import (
    Applicability,
    ApplicabilityState,
    AuditContext,
    default_rules,
    run_audit,
)
from lacuna.signal import decay
from lacuna.types import AnalysisResult, Finding, FindingState, ResultMetadata, Severity


def _result(
    method: str,
    metrics: dict[str, object],
    tables: dict[str, object] | None = None,
) -> AnalysisResult:
    return AnalysisResult(
        metadata=ResultMetadata(
            method=method,
            parameters={"price_adjustment": "raw"} if method == "labels.forward_returns" else {},
        ),
        metrics=metrics,
        tables=tables or {},
    )


def _decay(mean_ics: dict[str, float | None]) -> AnalysisResult:
    return _result(
        "signal.decay",
        {"n_horizons": len(mean_ics)},
        {"ic_decay": [{"horizon": name, "mean_ic": value} for name, value in mean_ics.items()]},
    )


def _complete_context() -> AuditContext:
    return AuditContext(
        results={
            "ic": _result("signal.ic", {"mean_ic": 0.08, "n_periods": 80}),
            "quantiles": _result("signal.quantiles", {"spearman_monotonicity": 0.9}),
            "bootstrap": _result(
                "validation.bootstrap",
                {
                    "observed": 0.08,
                    "confidence_lower": 0.01,
                    "confidence_upper": 0.15,
                    "n_raw": 80,
                },
            ),
            "decay": _decay({"1D": 0.08, "5D": 0.05, "20D": 0.02}),
            "labels": _result("labels.forward_returns", {"n_labels": 1_000}),
            "split": _result("cv.purged_kfold", {"purged_observations": 24}),
            "turnover": _result("signal.turnover", {"mean_rank_turnover": 0.2}),
        },
        policies={
            "study_type": "signal",
            "survivorship_safe": True,
            "trial_history_available": True,
        },
    )


def test_missing_evidence_is_unknown_and_signal_costs_are_not_applicable() -> None:
    result = run_audit(AuditContext(policies={"study_type": "signal"}))
    states = {finding.code: finding.state for finding in result.findings}

    assert states["IC_DEFINED"] == FindingState.UNKNOWN
    assert states["TRANSACTION_COST_EVIDENCE"] == FindingState.NOT_APPLICABLE
    assert result.metrics["unknown_count"] == 12
    assert result.metrics["not_applicable_count"] == 1
    assert result.metrics["robustness_score"] == 0.0
    assert result.metrics["evidence_coverage"] == 0.0


def test_context_deeply_freezes_declared_policies() -> None:
    nested: dict[str, object] = {"source": {"status": "declared"}}
    context = AuditContext(policies=nested)  # type: ignore[arg-type]
    nested_source = nested["source"]
    assert isinstance(nested_source, dict)
    nested_source["status"] = "mutated"

    frozen_source = context.policies["source"]
    assert isinstance(frozen_source, dict | type(context.policies))
    assert frozen_source["status"] == "declared"  # type: ignore[index]


def test_complete_evidence_scores_one_hundred_without_hiding_na() -> None:
    result = run_audit(_complete_context())

    assert result.metrics["robustness_score"] == 100.0
    assert result.metrics["evidence_coverage"] == 1.0
    assert result.metrics["failure_count"] == 0
    assert result.metrics["warning_count"] == 0
    assert result.metrics["unknown_count"] == 0
    assert result.metrics["not_applicable_count"] == 1


@dataclass(frozen=True)
class _StaticRule:
    rule_id: str
    state: FindingState
    weight: float = 1.0
    severity: Severity = Severity.MEDIUM
    category: str = "test"
    title: str = "Static rule"
    rule_version: int = 1

    def applicable(self, context: AuditContext) -> Applicability:
        del context
        if self.state == FindingState.NOT_APPLICABLE:
            return Applicability(ApplicabilityState.NOT_APPLICABLE, "not relevant")
        if self.state == FindingState.UNKNOWN:
            return Applicability(ApplicabilityState.UNKNOWN, "evidence missing")
        return Applicability(ApplicabilityState.APPLICABLE, "available")

    def evaluate(self, context: AuditContext) -> Finding:
        del context
        return Finding(
            code=self.rule_id,
            title=self.title,
            message="static outcome",
            state=self.state,
            severity=self.severity,
            category=self.category,
        )


def test_score_credit_and_coverage_cover_every_applicability_state() -> None:
    rules = tuple(
        _StaticRule(name, state)
        for name, state in (
            ("PASS", FindingState.PASS),
            ("WARN", FindingState.WARN),
            ("FAIL", FindingState.FAIL),
            ("UNKNOWN", FindingState.UNKNOWN),
            ("NA", FindingState.NOT_APPLICABLE),
        )
    )
    result = run_audit(AuditContext(), rules=rules)

    assert result.metrics["robustness_score"] == 37.5
    assert result.metrics["evidence_coverage"] == 0.75
    assert result.metrics["possible_weight"] == 4.0
    assert result.metrics["unknown_weight"] == 1.0


def test_rule_order_does_not_change_normalized_audit_output() -> None:
    rules = default_rules()
    first = run_audit(_complete_context(), rules=rules)
    second = run_audit(_complete_context(), rules=tuple(reversed(rules)))

    assert first.metrics == second.metrics
    assert first.tables == second.tables
    assert [finding.to_dict() for finding in first.findings] == [
        finding.to_dict() for finding in second.findings
    ]
    assert first.metadata.parameters == second.metadata.parameters


def test_duplicate_rule_identifiers_and_bad_rule_outputs_fail_closed() -> None:
    duplicate = _StaticRule("DUPLICATE", FindingState.PASS)
    with pytest.raises(ValueError, match="unique"):
        run_audit(AuditContext(), rules=(duplicate, duplicate))

    @dataclass(frozen=True)
    class WrongCodeRule(_StaticRule):
        def evaluate(self, context: AuditContext) -> Finding:
            finding = super().evaluate(context)
            return Finding(
                code="WRONG",
                title=finding.title,
                message=finding.message,
                state=finding.state,
            )

    with pytest.raises(ValueError, match="returned finding code"):
        run_audit(
            AuditContext(),
            rules=(WrongCodeRule("EXPECTED", FindingState.PASS),),
        )


@pytest.mark.parametrize("weight", [0.0, -1.0, float("inf"), float("nan")])
def test_invalid_rule_weights_are_rejected(weight: float) -> None:
    with pytest.raises(ValueError, match="positive and finite"):
        run_audit(
            AuditContext(),
            rules=(_StaticRule("WEIGHT", FindingState.PASS, weight=weight),),
        )


def test_unexpected_rule_exceptions_propagate() -> None:
    @dataclass(frozen=True)
    class BrokenRule(_StaticRule):
        def evaluate(self, context: AuditContext) -> Finding:
            del context
            raise RuntimeError("broken rule")

    with pytest.raises(RuntimeError, match="broken rule"):
        run_audit(AuditContext(), rules=(BrokenRule("BROKEN", FindingState.PASS),))


def test_non_purged_split_cannot_claim_temporal_validation_pass() -> None:
    context = _complete_context()
    results = dict(context.results)
    results["split"] = _result("cv.walk_forward", {"purged_observations": 0})
    result = run_audit(AuditContext(results=results, policies=context.policies))
    finding = next(
        finding for finding in result.findings if finding.code == "PURGED_VALIDATION_SUPPLIED"
    )
    assert finding.state == FindingState.UNKNOWN


def _decay_finding(decay: AnalysisResult) -> Finding:
    context = _complete_context()
    results = {**context.results, "decay": decay}
    result = run_audit(AuditContext(results=results, policies=context.policies))
    return next(finding for finding in result.findings if finding.code == "HORIZON_DECAY_COVERAGE")


def test_decay_coverage_counts_only_horizons_with_defined_ic() -> None:
    # Regression: rule v1 counted requested horizons, so a horizon with no defined IC
    # period still contributed to a three-horizon PASS.
    finding = _decay_finding(_decay({"1D": None, "5D": 0.05, "20D": 0.02}))

    assert finding.state == FindingState.WARN
    assert finding.evidence["rule_version"] == 2
    assert finding.evidence["n_horizons"] == 3
    assert finding.evidence["n_defined_horizons"] == 2
    assert finding.evidence["undefined_horizons"] == ("1D",)
    assert _decay_finding(_decay({"1D": None, "5D": None, "20D": 0.02})).state == (
        FindingState.FAIL
    )


@pytest.mark.parametrize("tables", [{}, {"ic_decay": []}, {"ic_decay": [{"horizon": "1D"}]}])
def test_decay_coverage_without_per_horizon_evidence_is_unknown(
    tables: dict[str, object],
) -> None:
    finding = _decay_finding(_result("signal.decay", {"n_horizons": 3}, tables))

    assert finding.state == FindingState.UNKNOWN
    assert "n_defined_horizons" not in finding.evidence


def test_decay_coverage_reads_real_decay_evidence_with_an_undefined_horizon() -> None:
    periods, instruments = 30, 6
    times = np.repeat(np.arange(periods), instruments)
    names = np.tile([f"asset-{index}" for index in range(instruments)], periods)
    rng = np.random.default_rng(3)
    signal = pl.DataFrame(
        {"time": times, "instrument": names, "signal": rng.normal(size=times.size)}
    )
    labels = pl.concat(
        [
            pl.DataFrame(
                {
                    "observation_time": times,
                    "instrument": names,
                    "horizon": horizon,
                    # A constant cross-section leaves every 1D period's rank IC undefined.
                    "forward_return": (
                        np.zeros(times.size) if horizon == "1D" else rng.normal(size=times.size)
                    ),
                }
            )
            for horizon in ("1D", "5D", "20D")
        ]
    )

    finding = _decay_finding(decay(signal, labels, use_native=False))

    assert finding.state == FindingState.WARN
    assert finding.evidence["n_defined_horizons"] == 2
    assert finding.evidence["undefined_horizons"] == ("1D",)


def _finding(code: str, name: str, evidence: AnalysisResult, **policies: object) -> Finding:
    context = _complete_context()
    results = {**context.results, name: evidence}
    merged = {**context.policies, **policies}
    result = run_audit(AuditContext(results=results, policies=merged))  # type: ignore[arg-type]
    return next(finding for finding in result.findings if finding.code == code)


def _multi_horizon_ic() -> AnalysisResult:
    # Pooled metrics blend both horizons; only the per-horizon rows are estimands.
    return _result(
        "signal.ic.spearman",
        {"mean_ic": 0.03, "n_periods": 130},
        {
            "ic_by_horizon": [
                {"horizon": "1D", "mean_ic": 0.05, "n_periods": 70},
                {"horizon": "20D", "mean_ic": None, "n_periods": 0},
            ]
        },
    )


@pytest.mark.parametrize("code", ["IC_DEFINED", "IC_PERIOD_SUPPORT"])
def test_multi_horizon_ic_without_a_declared_horizon_is_unknown(code: str) -> None:
    # Regression: v1 read pooled metrics, mixing horizons into one mean and period count.
    assert _finding(code, "ic", _multi_horizon_ic()).state == FindingState.UNKNOWN
    assert (
        _finding(code, "ic", _multi_horizon_ic(), inference_horizon="5D").state
        == FindingState.UNKNOWN
    )


def test_ic_rules_evaluate_the_declared_inference_horizon() -> None:
    defined = _finding("IC_DEFINED", "ic", _multi_horizon_ic(), inference_horizon="1D")
    support = _finding("IC_PERIOD_SUPPORT", "ic", _multi_horizon_ic(), inference_horizon="1D")
    undefined = _finding("IC_DEFINED", "ic", _multi_horizon_ic(), inference_horizon="20D")

    assert defined.state == FindingState.PASS
    assert defined.evidence["mean_ic"] == 0.05
    assert defined.evidence["rule_version"] == 2
    assert support.state == FindingState.PASS
    assert support.evidence["n_periods"] == 70
    assert undefined.state == FindingState.FAIL


def test_bootstrap_interval_needs_an_adequate_resampled_sample() -> None:
    def bootstrap(**metrics: object) -> AnalysisResult:
        base = {"observed": 0.08, "confidence_lower": 0.01, "confidence_upper": 0.15}
        return _result("validation.bootstrap", {**base, **metrics})

    small = _finding("BOOTSTRAP_INTERVAL", "bootstrap", bootstrap(n_raw=29))
    adequate = _finding("BOOTSTRAP_INTERVAL", "bootstrap", bootstrap(n_raw=30))
    unsized = _finding("BOOTSTRAP_INTERVAL", "bootstrap", bootstrap())

    assert small.state == FindingState.WARN
    assert small.evidence["n_resampled"] == 29
    assert adequate.state == FindingState.PASS
    assert adequate.evidence["rule_version"] == 2
    assert unsized.state == FindingState.UNKNOWN
