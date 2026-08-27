from __future__ import annotations

from datetime import UTC, datetime

import pytest

from lacuna._migration_benchmark import (
    MIGRATION_BENCHMARK_SCHEMA,
    MigrationAdmission,
    MigrationBenchmarkArtifact,
    MigrationBenchmarkTarget,
    MigrationMeasurement,
    _worker_payload,
    evaluate_admission,
    validate_artifact,
)
from lacuna.benchmark import BenchmarkConfig
from lacuna.exceptions import MethodContractError


def _measurement(
    *,
    seconds: float,
    checksum: str = "same",
    rss: int | None = 1_000,
) -> MigrationMeasurement:
    return MigrationMeasurement(
        case_name="case",
        backend="reference",
        timings_seconds=(seconds, seconds, seconds),
        median_seconds=seconds,
        minimum_seconds=seconds,
        maximum_seconds=seconds,
        median_absolute_deviation_seconds=0.0,
        throughput=100.0 / seconds,
        throughput_unit="rows/second",
        baseline_rss_bytes=10_000,
        process_peak_rss_bytes=None if rss is None else 10_000 + rss,
        incremental_peak_rss_bytes=rss,
        python_traced_peak_bytes=500,
        input_copy_bytes=None,
        output_copy_bytes=None,
        temporary_workspace_bytes=None,
        result_projection_bytes=None,
        phase_seconds={"public_call_total": seconds},
        checksum=checksum,
    )


def _target(**changes: object) -> MigrationBenchmarkTarget:
    values: dict[str, object] = {
        "candidate_id": "R-01",
        "public_operation": "signal.ic",
        "reference_case": "signal.ic.reference",
        "candidate_case": "signal.ic.native",
        "effective_dimensions": {"rows": 100_000, "groups": 200},
        "public_latency_share": 0.25,
    }
    values.update(changes)
    return MigrationBenchmarkTarget(**values)  # type: ignore[arg-type]


def test_admission_requires_correctness_before_performance() -> None:
    decision = evaluate_admission(
        _target(),
        _measurement(seconds=0.2, checksum="reference"),
        _measurement(seconds=0.05, checksum="candidate"),
    )
    assert decision.state == "NOT_MIGRATING"
    assert decision.correctness_match is False


def test_admission_accepts_material_transfer_inclusive_speedup() -> None:
    decision = evaluate_admission(
        _target(),
        _measurement(seconds=0.2),
        _measurement(seconds=0.1),
    )
    assert decision.state == "ADMITTED"
    assert decision.throughput_ratio == pytest.approx(2.0)


def test_admission_accepts_memory_reduction_without_latency_regression() -> None:
    decision = evaluate_admission(
        _target(),
        _measurement(seconds=0.2, rss=1_000),
        _measurement(seconds=0.21, rss=600),
    )
    assert decision.state == "ADMITTED"
    assert decision.rss_reduction_fraction == pytest.approx(0.4)


def test_admission_rejects_fast_but_immaterial_micro_case() -> None:
    decision = evaluate_admission(
        _target(public_latency_share=None),
        _measurement(seconds=0.01),
        _measurement(seconds=0.001),
    )
    assert decision.state == "NOT_MIGRATING"
    assert decision.material is False


def test_reference_only_target_remains_measured() -> None:
    target = _target(candidate_case=None, public_latency_share=0.20)
    decision = evaluate_admission(target, _measurement(seconds=0.01), None)
    assert decision.state == "MEASURED"
    assert decision.material is True


def test_artifact_is_finite_versioned_and_validated() -> None:
    reference = _measurement(seconds=0.2)
    candidate = _measurement(seconds=0.1)
    artifact = MigrationBenchmarkArtifact(
        target=_target(),
        config=BenchmarkConfig(repetitions=7, warmups=2),
        reference=reference,
        candidate=candidate,
        admission=MigrationAdmission(
            state="ADMITTED",
            material=True,
            correctness_match=True,
            throughput_ratio=2.0,
            rss_reduction_fraction=0.0,
            latency_regression_fraction=-0.5,
            reasons=("speed",),
        ),
        generated_at=datetime(2026, 8, 27, tzinfo=UTC),
        source_commit="abc123",
        run_url=None,
        environment={"python": "3.13"},
    )
    payload = artifact.to_dict()
    assert payload["schema"] == MIGRATION_BENCHMARK_SCHEMA
    validate_artifact(payload)


def test_artifact_validator_rejects_unknown_schema_and_state() -> None:
    with pytest.raises(MethodContractError):
        validate_artifact({"schema": "wrong", "version": 1})
    with pytest.raises(MethodContractError):
        validate_artifact(
            {
                "schema": MIGRATION_BENCHMARK_SCHEMA,
                "version": 1,
                "generated_at": "2026-08-27T00:00:00Z",
                "source_commit": "abc",
                "target": {},
                "config": {},
                "environment": {},
                "reference": {},
                "admission": {"state": "INVALID", "reasons": ["invalid"]},
            }
        )


def test_target_rejects_invalid_profile_shares() -> None:
    with pytest.raises(MethodContractError):
        _target(public_latency_share=1.1)


def test_private_fingerprint_cases_preserve_digest_without_public_benchmark_case() -> None:
    config = BenchmarkConfig(periods=30, instruments=20, repetitions=1, warmups=0)
    reference = _worker_payload("migration.fingerprint.array.reference", config, use_native=False)
    candidate = _worker_payload("migration.fingerprint.array.streaming", config, use_native=True)
    reference_measurement = reference["measurement"]
    candidate_measurement = candidate["measurement"]
    assert isinstance(reference_measurement, dict)
    assert isinstance(candidate_measurement, dict)
    assert reference_measurement["checksum"] == candidate_measurement["checksum"]
    assert reference_measurement["backend"] == "python_materialized_reference"
    assert candidate_measurement["backend"] == "python_streaming"


def test_timed_fingerprint_worker_skips_python_memory_trace() -> None:
    config = BenchmarkConfig(periods=30, instruments=20, repetitions=1, warmups=0)
    payload = _worker_payload(
        "migration.fingerprint.array.streaming",
        config,
        use_native=True,
        instrumented=False,
    )
    measurement = payload["measurement"]
    assert isinstance(measurement, dict)
    assert measurement["python_traced_peak_bytes"] == 0


def test_instrumented_native_pbo_reconciles_boundary_and_projection_bytes() -> None:
    config = BenchmarkConfig(
        periods=8,
        instruments=5,
        horizons=(1, 2),
        quantiles=3,
        bootstrap_resamples=100,
        repetitions=1,
        warmups=0,
    )
    payload = _worker_payload(
        "migration.validation.pbo.native",
        config,
        use_native=True,
        instrumented=True,
    )
    measurement = payload["measurement"]
    assert isinstance(measurement, dict)
    assert measurement["backend"] == "rust_native"
    assert measurement["input_copy_bytes"] == 1_440
    assert measurement["output_copy_bytes"] == 0
    assert measurement["temporary_workspace_bytes"] == 806
    assert measurement["result_projection_bytes"] == 840
    phases = measurement["phase_seconds"]
    assert isinstance(phases, dict)
    assert all(
        isinstance(phases[name], float) and phases[name] >= 0.0
        for name in ("normalization", "kernel", "result_projection", "result_construction")
    )


@pytest.mark.parametrize(
    "case_name",
    (
        "migration.costs.stress.public",
        "migration.costs.capacity.public",
        "migration.costs.break_even.public",
        "migration.validation.permutation.public",
        "migration.validation.pbo.public",
        "migration.validation.pbo.reference",
        "migration.validation.pbo.native",
        "migration.cv.cpcv.reference",
        "migration.signal.turnover.multilag",
        "migration.signal.portfolio.grouped_rank",
        "migration.regime.quantiles.rolling",
        "migration.events.windows.public",
        "migration.events.response.public",
        "migration.bias.universe_drift.public",
    ),
)
def test_private_migration_cases_measure_public_calls_without_extending_benchmark_v6(
    case_name: str,
) -> None:
    config = BenchmarkConfig(
        periods=8,
        instruments=5,
        horizons=(1, 2),
        quantiles=3,
        bootstrap_resamples=100,
        repetitions=1,
        warmups=0,
    )
    payload = _worker_payload(case_name, config, use_native=False, instrumented=False)
    measurement = payload["measurement"]
    assert isinstance(measurement, dict)
    assert measurement["case_name"] == case_name
    assert isinstance(measurement["backend"], str)
    assert measurement["backend"]
    assert measurement["python_traced_peak_bytes"] == 0
    assert len(str(measurement["checksum"])) == 64
