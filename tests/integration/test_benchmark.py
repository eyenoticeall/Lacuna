from __future__ import annotations

import json

import pytest

from lacuna.benchmark import BenchmarkConfig, benchmark_config_for_tier, run_benchmarks
from lacuna.exceptions import MethodContractError


def test_smoke_benchmark_runs_public_reference_and_native_paths() -> None:
    config = BenchmarkConfig(
        periods=8,
        instruments=5,
        horizons=(1, 2),
        quantiles=3,
        bootstrap_resamples=100,
        repetitions=1,
        warmups=0,
        seed=7,
    )
    suite = run_benchmarks(config)
    payload = json.loads(suite.to_json())
    names = {case["name"] for case in payload["cases"]}

    assert payload["schema_version"] == "1"
    assert payload["benchmark_version"] == 5
    assert payload["config"]["rows"] == 40
    assert "signal.ic.reference" in names
    assert "signal.ic.native" in names
    assert "validation.bootstrap.reference" in names
    assert "validation.bootstrap.native" in names
    assert "cv.purged_kfold.reference" in names
    assert "cv.purged_kfold.native" in names
    assert "cv.combinatorial_purged_kfold.reference" in names
    assert "validation.pbo.reference" in names
    assert "validation.reality_check.reference" in names
    assert "validation.spa.reference" in names
    assert "study.audit" in names
    assert "costs.stress.reference" in names
    assert "bias.asof_join.reference" in names
    assert "workflow.standard_audit.strategy" in names
    checksums = {case["name"]: case["checksum"] for case in payload["cases"]}
    assert checksums["signal.ic.reference"] == checksums["signal.ic.native"]
    assert checksums["validation.bootstrap.reference"] == checksums["validation.bootstrap.native"]
    assert checksums["cv.purged_kfold.reference"] == checksums["cv.purged_kfold.native"]
    for case in payload["cases"]:
        assert case["median_seconds"] >= 0.0
        assert case["throughput"] > 0.0
        assert len(case["checksum"]) == 64


def test_benchmark_checksums_are_repeatable_independent_of_timing() -> None:
    config = BenchmarkConfig(
        periods=7,
        instruments=5,
        horizons=(1, 2),
        quantiles=3,
        bootstrap_resamples=100,
        repetitions=1,
        warmups=0,
        seed=11,
    )
    first = run_benchmarks(config, use_native=False)
    second = run_benchmarks(config, use_native=False)
    assert {case.name: case.checksum for case in first.cases} == {
        case.name: case.checksum for case in second.cases
    }


def test_benchmark_configuration_rejects_invalid_contracts() -> None:
    with pytest.raises(MethodContractError):
        BenchmarkConfig(periods=3, horizons=(3,))
    with pytest.raises(MethodContractError):
        benchmark_config_for_tier("large")
