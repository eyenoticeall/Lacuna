"""Exercise an installed Lacuna wheel without development dependencies."""

from __future__ import annotations

import importlib
import json
import math
import tempfile
from importlib import metadata
from importlib.resources import files
from pathlib import Path

import numpy as np

import lacuna
from lacuna import _native
from lacuna.schemas import (
    audit_result_v1_text,
    bundle_manifest_v1_text,
    persisted_artifact_compatibility_v1_text,
    standard_audit_profile_v1_text,
)

PUBLIC_MODULES = (
    "lacuna.adapters",
    "lacuna.audit",
    "lacuna.audit_profiles",
    "lacuna.benchmark",
    "lacuna.bias",
    "lacuna.bundle",
    "lacuna.cli",
    "lacuna.config",
    "lacuna.costs",
    "lacuna.cv",
    "lacuna.diagnostics",
    "lacuna.events",
    "lacuna.experiment",
    "lacuna.labels",
    "lacuna.native",
    "lacuna.plugins",
    "lacuna.regime",
    "lacuna.report",
    "lacuna.robustness",
    "lacuna.signal",
    "lacuna.study",
    "lacuna.validation",
)


def require(condition: bool, message: str) -> None:
    """Fail the artifact smoke check with a useful contract message."""

    if not condition:
        raise RuntimeError(message)


for module in PUBLIC_MODULES:
    importlib.import_module(module)

distribution_version = metadata.version("lacuna-quant")
require(lacuna.__version__ == distribution_version, "package and distribution versions disagree")
require(_native.version() == distribution_version, "native and distribution versions disagree")
require(_native.checked_mean([1.0, 2.0, 3.0]) == 2.0, "native mean kernel failed")

installation = lacuna.diagnose_installation()
require(installation.status.value == "PASS", "installed-wheel diagnostics did not pass")
require(installation.healthy, "installed-wheel diagnostics reported an unhealthy runtime")
diagnostic_codes = {check.code for check in installation.checks}
require(
    {
        "AUDIT_RESULT_SCHEMA",
        "BUNDLE_MANIFEST_SCHEMA",
        "DISTRIBUTION_METADATA",
        "DISTRIBUTION_NAME_COLLISION",
        "NATIVE_CORE",
        "PACKAGE_VERSION",
        "PERSISTED_ARTIFACT_COMPATIBILITY",
        "PLATFORM_WHEEL",
        "PYTHON_RUNTIME",
        "RUNTIME_CONFIGURATION",
        "RUNTIME_DEPENDENCIES",
        "STANDARD_AUDIT_PROFILE_SCHEMA",
    }.issubset(diagnostic_codes),
    "installed-wheel diagnostics omitted a release check",
)

rank_ic, rank_ic_validity = _native.grouped_rank_ic(
    np.asarray([1.0, 2.0, 3.0, 1.0, 2.0], dtype=np.float64),
    np.asarray([0.0, -0.0, 1.0, 0.0, -0.0], dtype=np.float64),
    np.asarray([0, 3, 5], dtype=np.int64),
)
require(math.isclose(rank_ic[0], math.sqrt(3.0) / 2.0, abs_tol=1e-14), "native rank IC failed")
require(rank_ic_validity.tolist() == [1, 0], "signed-zero constant group must be undefined")

signal_result = lacuna.signal.ic(
    np.array([1.0, 2.0, 3.0]),
    np.array([1.0, 2.0, 3.0]),
    by=None,
    min_observations=2,
)
require(signal_result.metrics["mean_ic"] == 1.0, "public signal API failed")

registry = lacuna.ExperimentRegistry("wheel-smoke")
registry.record(parameters={"trial": 1}, metric=0.01, metric_name="p_value")
registry.record(parameters={"trial": 2}, metric=0.20, metric_name="p_value")
adjusted = lacuna.validation.multiple_testing(registry, method="holm")
require(adjusted.metrics["trial_count"] == 2, "experiment/multiple-testing API failed")

regimes = lacuna.regime.quantile_regimes(
    {"time": [0, 1, 2], "value": [1.0, 2.0, 3.0]},
    method="fixed",
    lower_threshold=1.5,
    upper_threshold=2.5,
)
require(regimes.metrics["classified_rows"] == 3, "regime API failed")

cost_stress = lacuna.costs.stress(
    {
        "decision_time": [0, 1],
        "execution_time": [0, 1],
        "instrument": ["A", "B"],
        "side": ["buy", "sell"],
        "quantity": [10.0, -10.0],
        "price": [100.0, 100.0],
        "reference_price": [100.0, 100.0],
        "gross_pnl": [10.0, 10.0],
    },
    spread_bps=(0.0, 10.0),
    slippage_bps=(0.0,),
)
require(cost_stress.metrics["scenario_count"] == 2, "cost stress API failed")
require(cost_stress.metrics["worst_net_pnl"] == 19.0, "cost stress valuation failed")

point_in_time = lacuna.bias.asof_join(
    {
        "decision_time": [2, 4],
        "instrument": ["A", "A"],
    },
    {
        "available_time": [1, 3, 5],
        "instrument": ["A", "A", "A"],
        "value": [10.0, 30.0, 50.0],
    },
    revision_mode="not_applicable",
)
require(
    point_in_time.frame.get_column("value").to_list() == [10.0, 30.0],
    "point-in-time join selected the wrong versions",
)
require(
    point_in_time.evidence.metrics["future_matches"] == 0,
    "point-in-time join selected future data",
)

intervals = {
    "observation_time": list(range(6)),
    "label_start": list(range(6)),
    "label_end": [value + 1 for value in range(6)],
}
combinatorial = lacuna.cv.CombinatorialPurgedKFold(
    n_groups=3,
    n_test_groups=1,
).split(intervals)
require(len(combinatorial.folds) == 3, "CPCV combination generation failed")
require(len(combinatorial.paths) == 1, "CPCV path reconstruction failed")

inference_matrix = np.column_stack(
    (
        np.sin(np.arange(12, dtype=np.float64)) + 1.0,
        np.cos(np.arange(12, dtype=np.float64)),
        np.sin(np.arange(12, dtype=np.float64) * 0.5) - 1.0,
    )
)
pbo = lacuna.validation.probability_of_backtest_overfitting(
    inference_matrix,
    partitions=4,
    statistic="mean",
)
require(pbo.metrics["n_combinations"] == 6, "CSCV/PBO inference failed")
permutation = lacuna.validation.permutation_test(
    inference_matrix[:, 0],
    permutations=100,
    seed=7,
)
require(0.0 < permutation.metrics["p_value"] <= 1.0, "permutation inference failed")
sharpe = lacuna.validation.sharpe_inference(inference_matrix[:, 0])
require(
    sharpe.metrics["probabilistic_sharpe_ratio"] > 0.5,
    "Sharpe inference failed",
)
reality = lacuna.validation.reality_check(
    inference_matrix,
    expected_block_length=1,
    resamples=100,
    seed=7,
)
spa = lacuna.validation.superior_predictive_ability(
    inference_matrix,
    expected_block_length=1,
    resamples=100,
    seed=7,
)
require(0.0 < reality.metrics["p_value"] <= 1.0, "Reality Check inference failed")
require(0.0 < spa.metrics["p_value_consistent"] <= 1.0, "SPA inference failed")

vendor = lacuna.adapters.adapt_vendor(
    {"asset": ["A"], "published": [1], "metric": [2.0]},
    lacuna.adapters.VendorSchema(
        "wheel-smoke.vendor.v1",
        {"instrument": "asset", "available_time": "published", "value": "metric"},
        required=("instrument", "available_time", "value"),
        availability="point_in_time",
    ),
    collect=True,
)
require(vendor.columns == ("instrument", "available_time", "value"), "vendor adapter failed")

backtest = lacuna.adapters.adapt_backtest(
    {"date": [1], "model": ["alpha"], "pnl_return": [0.01]},
    lacuna.adapters.BacktestSchema(
        "wheel-smoke.backtest.v1",
        "returns",
        {"time": "date", "strategy": "model", "return": "pnl_return"},
        lacuna.adapters.BacktestSemantics(
            returns="net",
            return_frequency="daily",
            compounding="simple",
            position_timing="close-to-close",
            execution_delay="one session",
            price_field="close",
            price_adjustment="total_return_adjusted",
            costs="included",
            borrow="included",
            timezone="UTC",
            calendar="XNYS",
            session="regular",
            missing_instruments="retain as null",
            delistings="terminal return included",
        ),
    ),
    collect=True,
)
require(backtest.columns == ("time", "strategy", "return"), "backtest adapter failed")

factor_panel = lacuna.adapters.adapt_factor_panel(
    {"date": [1], "asset": ["A"], "factor": [0.25]},
    lacuna.adapters.FactorPanelSchema(
        "wheel-smoke.factor-panel.v1",
        {"observation_time": "date", "instrument": "asset", "signal": "factor"},
        lacuna.adapters.FactorPanelSemantics(
            signal_observation="synthetic",
            decision_time_rule="synthetic",
            forward_return_entry="not_applicable",
            forward_return_exit="not_applicable",
            horizon_clock="trading_observations",
            timezone="UTC",
            calendar="synthetic",
            adjustment_policy="not_applicable",
            group_availability="not_applicable",
            imported_bucket_definition="not_applicable",
        ),
    ),
)
require(
    factor_panel.columns == ("observation_time", "instrument", "signal"),
    "factor-panel adapter failed",
)

sklearn_cv = lacuna.adapters.as_sklearn_cv(
    lacuna.cv.WalkForward(train=2, test=1, step=1),
    {"time": [0, 1, 2, 3]},
)
require(sklearn_cv.get_n_splits() == 2, "sklearn CV adapter failed")


class _DuckDBSmokeSource:
    def to_arrow_reader(self, batch_size: int) -> object:
        require(batch_size == 1, "DuckDB adapter batch size changed")
        return {"value": [1.0]}


duckdb_frame = lacuna.adapters.from_duckdb(_DuckDBSmokeSource(), batch_size=1)
require(duckdb_frame.evidence.metrics["row_count"] == 1, "DuckDB adapter failed")
plugin_candidates = lacuna.plugins.discover_plugins()
require(isinstance(plugin_candidates, tuple), "plugin discovery failed")

standard_report = lacuna.standard_audit(
    results={
        "vendor": vendor.evidence,
        "backtest": backtest.evidence,
        "costs": cost_stress,
        "point_in_time": point_in_time.evidence,
    },
    scope="strategy",
)
require(
    standard_report.metrics["recognized_result_count"] == 4,
    "standardized audit did not recognize installed-wheel evidence",
)
require(
    "robustness_score" not in standard_report.metrics,
    "standardized audit must not emit one universal score",
)
round_tripped = lacuna.AnalysisResult.from_json(standard_report.to_json())
require(
    round_tripped.to_dict() == standard_report.result.to_dict(),
    "strict result JSON reader did not round-trip the standardized audit",
)

bundle_report = lacuna.audit(policies={"study_type": "signal"})
with tempfile.TemporaryDirectory() as temporary_directory:
    bundle_path = bundle_report.bundle(Path(temporary_directory) / "wheel-smoke.lacuna")
    bundle_verification = lacuna.verify_bundle(bundle_path)
require(bundle_verification.artifact_count == 5, "reproducibility bundle verification failed")

package = files("lacuna")
require(package.joinpath("py.typed").is_file(), "wheel is missing py.typed")
require(package.joinpath("_native.pyi").is_file(), "wheel is missing native type stubs")
schema = json.loads(audit_result_v1_text())
require(schema.get("title") == "Lacuna audit result v1", "wheel is missing the audit schema")
bundle_schema = json.loads(bundle_manifest_v1_text())
require(
    bundle_schema.get("title") == "Lacuna reproducibility bundle manifest v1",
    "wheel is missing the bundle schema",
)
profile_schema = json.loads(standard_audit_profile_v1_text())
require(
    profile_schema.get("title") == "Lacuna standardized audit profile v1",
    "wheel is missing the standardized audit profile schema",
)
compatibility = json.loads(persisted_artifact_compatibility_v1_text())
require(
    compatibility.get("format") == "lacuna.persisted-artifact-compatibility",
    "wheel is missing the persisted-artifact compatibility manifest",
)
require(
    lacuna.AuditProfile.from_json(json.dumps(lacuna.standard_profile("strategy").to_dict()))
    == lacuna.standard_profile("strategy"),
    "installed profile-v1 strict reader failed",
)

print(
    json.dumps(
        {
            "distribution_version": distribution_version,
            "diagnostic_status": installation.status.value,
            "native_version": _native.version(),
            "public_modules": len(PUBLIC_MODULES),
            "schema": schema["title"],
            "signal_mean_ic": signal_result.metrics["mean_ic"],
            "trial_count": adjusted.metrics["trial_count"],
            "cost_scenarios": cost_stress.metrics["scenario_count"],
            "point_in_time_matches": point_in_time.evidence.metrics["matched_rows"],
            "plugin_candidates": len(plugin_candidates),
            "bundle_artifacts": bundle_verification.artifact_count,
            "cpcv_combinations": len(combinatorial.folds),
            "pbo_combinations": pbo.metrics["n_combinations"],
            "reality_check_p_value": reality.metrics["p_value"],
            "spa_p_value": spa.metrics["p_value_consistent"],
        },
        indent=2,
        sort_keys=True,
    )
)
