from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from lacuna.audit import AuditContext
from lacuna.audit_profiles import run_standard_audit, standard_profile
from lacuna.schemas import standard_audit_profile_v1_text
from lacuna.types import AnalysisResult, ResultMetadata

ROOT = Path(__file__).parents[2]
SCHEMA_PATH = ROOT / "schemas" / "standard-audit-profile-v1.schema.json"
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "standard-audit-profile-v1.json"

RELEASED_METHODS = (
    "labels.forward_returns",
    "signal.ic.spearman",
    "signal.quantiles",
    "signal.turnover",
    "signal.decay",
    "cv.walk_forward",
    "cv.purged_kfold",
    "cv.combinatorial_purged_kfold",
    "validation.bootstrap.stationary",
    "validation.permutation.circular_shift",
    "validation.sharpe_inference",
    "validation.probability_of_backtest_overfitting",
    "validation.joint_stationary_bootstrap",
    "validation.white_reality_check",
    "validation.hansen_spa",
    "validation.multiple_testing.holm",
    "validation.parameter_surface",
    "experiment.registry_snapshot",
    "robustness.continuous_perturbation",
    "robustness.subperiod_analysis",
    "robustness.universe_perturbation",
    "regime.quantile_regimes",
    "regime.analysis",
    "costs.commission",
    "costs.stress",
    "costs.break_even_cost",
    "costs.liquidity_diagnostics",
    "costs.capacity_curve",
    "bias.asof_join",
    "bias.future_data_check",
    "bias.revision_diagnostics",
    "bias.survivorship_diagnostics",
    "bias.membership_at",
    "bias.universe_drift",
    "bias.validate_dataset",
    "adapters.vendor_schema",
    "adapters.backtest_artifact",
    "adapters.duckdb_arrow",
    "plugins.activate",
    "options.validate_chain",
    "options.delta_buckets",
    "options.empirical_residual",
)


def _validator() -> Draft202012Validator:
    return Draft202012Validator(
        json.loads(SCHEMA_PATH.read_text(encoding="utf-8")),
        format_checker=FormatChecker(),
    )


def test_published_and_packaged_profile_schemas_are_identical() -> None:
    assert standard_audit_profile_v1_text() == SCHEMA_PATH.read_text(encoding="utf-8")


def test_every_builtin_profile_and_the_frozen_strategy_fixture_validate() -> None:
    validator = _validator()
    for scope in ("signal", "strategy", "options"):
        validator.validate(standard_profile(scope).to_dict())

    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    validator.validate(fixture)
    assert fixture == standard_profile("strategy").to_dict()


def test_every_released_result_method_maps_to_exactly_one_profile_capability() -> None:
    requirements = standard_profile("strategy").requirements
    for method in RELEASED_METHODS:
        matches = [item.capability_id for item in requirements if item.matches(method)]
        assert len(matches) == 1, (method, matches)


def test_standardized_result_remains_in_the_published_result_envelope() -> None:
    results = {
        method: AnalysisResult(metadata=ResultMetadata(method=method))
        for method in RELEASED_METHODS
    }
    result = run_standard_audit(AuditContext(results=results), scope="strategy")
    audit_schema = json.loads((ROOT / "schemas" / "audit-result-v1.schema.json").read_text())
    Draft202012Validator(audit_schema, format_checker=FormatChecker()).validate(result.to_dict())
    assert result.metrics["unrecognized_result_count"] == 0
