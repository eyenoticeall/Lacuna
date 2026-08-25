"""Exercise an installed Lacuna wheel without development dependencies."""

from __future__ import annotations

import importlib
import json
import math
from importlib import metadata
from importlib.resources import files

import numpy as np

import lacuna
from lacuna import _native
from lacuna.schemas import audit_result_v1_text

PUBLIC_MODULES = (
    "lacuna.adapters",
    "lacuna.audit",
    "lacuna.benchmark",
    "lacuna.bias",
    "lacuna.cli",
    "lacuna.config",
    "lacuna.costs",
    "lacuna.cv",
    "lacuna.experiment",
    "lacuna.labels",
    "lacuna.native",
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

distribution_version = metadata.version("lacuna")
require(lacuna.__version__ == distribution_version, "package and distribution versions disagree")
require(_native.version() == distribution_version, "native and distribution versions disagree")
require(_native.checked_mean([1.0, 2.0, 3.0]) == 2.0, "native mean kernel failed")

rank_ic = _native.grouped_rank_ic(
    [1.0, 2.0, 3.0, 1.0, 2.0],
    [0.0, -0.0, 1.0, 0.0, -0.0],
    [0, 3, 5],
)
require(rank_ic[0] is not None, "native rank IC unexpectedly undefined")
require(math.isclose(rank_ic[0], math.sqrt(3.0) / 2.0, abs_tol=1e-14), "native rank IC failed")
require(rank_ic[1] is None, "signed-zero constant group must be undefined")

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

package = files("lacuna")
require(package.joinpath("py.typed").is_file(), "wheel is missing py.typed")
require(package.joinpath("_native.pyi").is_file(), "wheel is missing native type stubs")
schema = json.loads(audit_result_v1_text())
require(schema.get("title") == "Lacuna audit result v1", "wheel is missing the audit schema")

print(
    json.dumps(
        {
            "distribution_version": distribution_version,
            "native_version": _native.version(),
            "public_modules": len(PUBLIC_MODULES),
            "schema": schema["title"],
            "signal_mean_ic": signal_result.metrics["mean_ic"],
            "trial_count": adjusted.metrics["trial_count"],
            "cost_scenarios": cost_stress.metrics["scenario_count"],
            "point_in_time_matches": point_in_time.evidence.metrics["matched_rows"],
            "cpcv_combinations": len(combinatorial.folds),
            "pbo_combinations": pbo.metrics["n_combinations"],
            "reality_check_p_value": reality.metrics["p_value"],
            "spa_p_value": spa.metrics["p_value_consistent"],
        },
        indent=2,
        sort_keys=True,
    )
)
