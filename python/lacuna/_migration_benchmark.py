"""Private isolated benchmark and admission evidence for native migration work."""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Literal, cast

from lacuna.benchmark import BenchmarkConfig, _run_benchmark_case_detailed
from lacuna.exceptions import MethodContractError

MIGRATION_BENCHMARK_SCHEMA = "lacuna.native-migration-benchmark"
MIGRATION_BENCHMARK_VERSION = 1

MigrationState = Literal[
    "PROPOSED",
    "MEASURED",
    "ADMITTED",
    "SHIPPED_NATIVE",
    "OPTIMIZED_NON_NATIVE",
    "NOT_MIGRATING",
    "BLOCKED",
]


@dataclass(frozen=True, slots=True)
class MigrationBenchmarkTarget:
    """Private description of one reference/candidate public-call comparison."""

    candidate_id: str
    public_operation: str
    reference_case: str
    candidate_case: str | None
    effective_dimensions: Mapping[str, int | float | str | bool | None]
    public_latency_share: float | None = None
    public_rss_share: float | None = None
    asymptotic_or_unbounded: bool = False
    bounded_memory_advantage: bool = False

    def __post_init__(self) -> None:
        if not self.candidate_id or not self.public_operation or not self.reference_case:
            raise MethodContractError("migration benchmark target identifiers must be non-empty")
        for name, share in (
            ("public_latency_share", self.public_latency_share),
            ("public_rss_share", self.public_rss_share),
        ):
            if share is not None and (not math.isfinite(share) or not 0.0 <= share <= 1.0):
                raise MethodContractError(f"{name} must be a finite fraction in [0, 1]")
        for key, value in self.effective_dimensions.items():
            if not key:
                raise MethodContractError("effective dimension names must be non-empty")
            if isinstance(value, float) and not math.isfinite(value):
                raise MethodContractError("effective dimensions must contain finite values")


@dataclass(frozen=True, slots=True)
class MigrationMeasurement:
    """Raw same-process evidence for one measured backend."""

    case_name: str
    backend: str
    timings_seconds: tuple[float, ...]
    median_seconds: float
    minimum_seconds: float
    maximum_seconds: float
    median_absolute_deviation_seconds: float
    throughput: float
    throughput_unit: str
    baseline_rss_bytes: int | None
    process_peak_rss_bytes: int | None
    incremental_peak_rss_bytes: int | None
    python_traced_peak_bytes: int
    input_copy_bytes: int | None
    output_copy_bytes: int | None
    temporary_workspace_bytes: int | None
    result_projection_bytes: int | None
    phase_seconds: Mapping[str, float | None]
    checksum: str

    def to_dict(self) -> dict[str, object]:
        """Return finite JSON-compatible measurement evidence."""

        return {
            "case_name": self.case_name,
            "backend": self.backend,
            "timings_seconds": list(self.timings_seconds),
            "median_seconds": self.median_seconds,
            "minimum_seconds": self.minimum_seconds,
            "maximum_seconds": self.maximum_seconds,
            "median_absolute_deviation_seconds": self.median_absolute_deviation_seconds,
            "throughput": self.throughput,
            "throughput_unit": self.throughput_unit,
            "baseline_rss_bytes": self.baseline_rss_bytes,
            "process_peak_rss_bytes": self.process_peak_rss_bytes,
            "incremental_peak_rss_bytes": self.incremental_peak_rss_bytes,
            "python_traced_peak_bytes": self.python_traced_peak_bytes,
            "input_copy_bytes": self.input_copy_bytes,
            "output_copy_bytes": self.output_copy_bytes,
            "temporary_workspace_bytes": self.temporary_workspace_bytes,
            "result_projection_bytes": self.result_projection_bytes,
            "phase_seconds": dict(self.phase_seconds),
            "checksum": self.checksum,
        }


@dataclass(frozen=True, slots=True)
class MigrationAdmission:
    """Mechanical v0.14 materiality and native-admission decision."""

    state: MigrationState
    material: bool
    correctness_match: bool | None
    throughput_ratio: float | None
    rss_reduction_fraction: float | None
    latency_regression_fraction: float | None
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        """Return JSON-compatible admission evidence."""

        return {
            "state": self.state,
            "material": self.material,
            "correctness_match": self.correctness_match,
            "throughput_ratio": self.throughput_ratio,
            "rss_reduction_fraction": self.rss_reduction_fraction,
            "latency_regression_fraction": self.latency_regression_fraction,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True, slots=True)
class MigrationBenchmarkArtifact:
    """Versioned private sidecar retaining one admission comparison."""

    target: MigrationBenchmarkTarget
    config: BenchmarkConfig
    reference: MigrationMeasurement
    candidate: MigrationMeasurement | None
    admission: MigrationAdmission
    generated_at: datetime
    source_commit: str
    run_url: str | None
    environment: Mapping[str, object]
    schema: str = MIGRATION_BENCHMARK_SCHEMA
    version: int = MIGRATION_BENCHMARK_VERSION

    def to_dict(self) -> dict[str, object]:
        """Return the canonical sidecar mapping."""

        return {
            "schema": self.schema,
            "version": self.version,
            "generated_at": self.generated_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "source_commit": self.source_commit,
            "run_url": self.run_url,
            "target": {
                "candidate_id": self.target.candidate_id,
                "public_operation": self.target.public_operation,
                "reference_case": self.target.reference_case,
                "candidate_case": self.target.candidate_case,
                "effective_dimensions": dict(self.target.effective_dimensions),
                "public_latency_share": self.target.public_latency_share,
                "public_rss_share": self.target.public_rss_share,
                "asymptotic_or_unbounded": self.target.asymptotic_or_unbounded,
                "bounded_memory_advantage": self.target.bounded_memory_advantage,
            },
            "config": _config_payload(self.config),
            "environment": dict(self.environment),
            "reference": self.reference.to_dict(),
            "candidate": None if self.candidate is None else self.candidate.to_dict(),
            "admission": self.admission.to_dict(),
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        """Serialize with finite numbers and stable key ordering."""

        return json.dumps(self.to_dict(), allow_nan=False, indent=indent, sort_keys=True)


def _config_payload(config: BenchmarkConfig) -> dict[str, object]:
    return {
        "periods": config.periods,
        "instruments": config.instruments,
        "horizons": list(config.horizons),
        "quantiles": config.quantiles,
        "bootstrap_resamples": config.bootstrap_resamples,
        "repetitions": config.repetitions,
        "warmups": config.warmups,
        "seed": config.seed,
    }


def _config_from_payload(payload: Mapping[str, object]) -> BenchmarkConfig:
    horizons_value = payload.get("horizons")
    if not isinstance(horizons_value, list) or not all(
        isinstance(value, int) and not isinstance(value, bool) for value in horizons_value
    ):
        raise MethodContractError("worker benchmark horizons must be an integer list")

    def integer(name: str) -> int:
        value = payload.get(name)
        if not isinstance(value, int) or isinstance(value, bool):
            raise MethodContractError(f"worker benchmark {name} must be an integer")
        return value

    return BenchmarkConfig(
        periods=integer("periods"),
        instruments=integer("instruments"),
        horizons=tuple(horizons_value),
        quantiles=integer("quantiles"),
        bootstrap_resamples=integer("bootstrap_resamples"),
        repetitions=integer("repetitions"),
        warmups=integer("warmups"),
        seed=integer("seed"),
    )


def _median_absolute_deviation(values: Sequence[float]) -> float:
    center = statistics.median(values)
    return statistics.median(abs(value - center) for value in values)


def _measurement_from_worker(payload: Mapping[str, object]) -> MigrationMeasurement:
    timings_value = payload.get("timings_seconds")
    if not isinstance(timings_value, list) or not timings_value:
        raise MethodContractError("worker timings must be a non-empty list")
    timings: tuple[float, ...] = tuple(float(value) for value in timings_value)
    if any(not math.isfinite(value) or value < 0.0 for value in timings):
        raise MethodContractError("worker timings must be finite and non-negative")

    def string(name: str) -> str:
        value = payload.get(name)
        if not isinstance(value, str) or not value:
            raise MethodContractError(f"worker {name} must be a non-empty string")
        return value

    def optional_integer(name: str) -> int | None:
        value = payload.get(name)
        if value is None:
            return None
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise MethodContractError(f"worker {name} must be a non-negative integer or null")
        return value

    median_seconds = statistics.median(timings)
    throughput_value = payload.get("throughput")
    if not isinstance(throughput_value, int | float) or isinstance(throughput_value, bool):
        raise MethodContractError("worker throughput must be numeric")
    throughput = float(throughput_value)
    if not math.isfinite(throughput) or throughput <= 0.0:
        raise MethodContractError("worker throughput must be finite and positive")
    traced = optional_integer("python_traced_peak_bytes")
    assert traced is not None
    return MigrationMeasurement(
        case_name=string("case_name"),
        backend=string("backend"),
        timings_seconds=timings,
        median_seconds=median_seconds,
        minimum_seconds=min(timings),
        maximum_seconds=max(timings),
        median_absolute_deviation_seconds=_median_absolute_deviation(timings),
        throughput=throughput,
        throughput_unit=string("throughput_unit"),
        baseline_rss_bytes=optional_integer("baseline_rss_bytes"),
        process_peak_rss_bytes=optional_integer("process_peak_rss_bytes"),
        incremental_peak_rss_bytes=optional_integer("incremental_peak_rss_bytes"),
        python_traced_peak_bytes=traced,
        input_copy_bytes=optional_integer("input_copy_bytes"),
        output_copy_bytes=optional_integer("output_copy_bytes"),
        temporary_workspace_bytes=optional_integer("temporary_workspace_bytes"),
        result_projection_bytes=optional_integer("result_projection_bytes"),
        phase_seconds={
            "normalization": None,
            "input_copy": None,
            "kernel": None,
            "result_projection": None,
            "result_construction": None,
            "public_call_total": median_seconds,
        },
        checksum=string("checksum"),
    )


def evaluate_admission(
    target: MigrationBenchmarkTarget,
    reference: MigrationMeasurement,
    candidate: MigrationMeasurement | None,
) -> MigrationAdmission:
    """Apply the mechanical materiality and v0.14 native admission thresholds."""

    material = (
        reference.median_seconds >= 0.05
        or (target.public_latency_share or 0.0) >= 0.15
        or (target.public_rss_share or 0.0) >= 0.15
        or target.asymptotic_or_unbounded
    )
    if candidate is None:
        return MigrationAdmission(
            state="MEASURED",
            material=material,
            correctness_match=None,
            throughput_ratio=None,
            rss_reduction_fraction=None,
            latency_regression_fraction=None,
            reasons=("reference measured; no candidate backend was supplied",),
        )

    correctness_match = reference.checksum == candidate.checksum
    throughput_ratio = reference.median_seconds / candidate.median_seconds
    latency_regression = (
        candidate.median_seconds - reference.median_seconds
    ) / reference.median_seconds
    rss_reduction: float | None = None
    if (
        reference.incremental_peak_rss_bytes is not None
        and reference.incremental_peak_rss_bytes > 0
        and candidate.incremental_peak_rss_bytes is not None
    ):
        rss_reduction = (
            reference.incremental_peak_rss_bytes - candidate.incremental_peak_rss_bytes
        ) / reference.incremental_peak_rss_bytes

    if not correctness_match:
        return MigrationAdmission(
            state="NOT_MIGRATING",
            material=material,
            correctness_match=False,
            throughput_ratio=throughput_ratio,
            rss_reduction_fraction=rss_reduction,
            latency_regression_fraction=latency_regression,
            reasons=("reference and candidate equivalence checksums differ",),
        )
    if not material:
        return MigrationAdmission(
            state="NOT_MIGRATING",
            material=False,
            correctness_match=True,
            throughput_ratio=throughput_ratio,
            rss_reduction_fraction=rss_reduction,
            latency_regression_fraction=latency_regression,
            reasons=("operation did not pass the materiality screen",),
        )

    throughput_pass = throughput_ratio >= 1.5
    memory_pass = rss_reduction is not None and rss_reduction >= 0.30 and latency_regression <= 0.10
    bounded_pass = target.bounded_memory_advantage
    if throughput_pass or memory_pass or bounded_pass:
        reasons: list[str] = []
        if throughput_pass:
            reasons.append("end-to-end throughput is at least 1.5x the optimized reference")
        if memory_pass:
            reasons.append("incremental RSS is at least 30% lower without >10% latency regression")
        if bounded_pass:
            reasons.append("candidate completed within a budget the reference exceeded")
        return MigrationAdmission(
            state="ADMITTED",
            material=True,
            correctness_match=True,
            throughput_ratio=throughput_ratio,
            rss_reduction_fraction=rss_reduction,
            latency_regression_fraction=latency_regression,
            reasons=tuple(reasons),
        )
    return MigrationAdmission(
        state="NOT_MIGRATING",
        material=True,
        correctness_match=True,
        throughput_ratio=throughput_ratio,
        rss_reduction_fraction=rss_reduction,
        latency_regression_fraction=latency_regression,
        reasons=("candidate did not meet throughput, memory, or bounded-completion admission",),
    )


def _worker_command(case_name: str, config: BenchmarkConfig, *, use_native: bool) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "lacuna._migration_benchmark",
        "worker",
        "--case",
        case_name,
        "--config-json",
        json.dumps(_config_payload(config), separators=(",", ":")),
    ]
    if use_native:
        command.append("--use-native")
    return command


def _run_worker(
    case_name: str, config: BenchmarkConfig, *, use_native: bool
) -> tuple[MigrationMeasurement, Mapping[str, object]]:
    environment = os.environ.copy()
    environment.update(
        {
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "OMP_NUM_THREADS": "1",
            "POLARS_MAX_THREADS": "2",
            "LACUNA_NATIVE_THREADS": "1",
        }
    )
    completed = subprocess.run(
        _worker_command(case_name, config, use_native=use_native),
        check=False,
        capture_output=True,
        env=environment,
        text=True,
    )
    if completed.returncode != 0:
        diagnostic = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"isolated migration worker failed for {case_name!r}: {diagnostic}")
    decoded = json.loads(completed.stdout)
    if not isinstance(decoded, dict):
        raise MethodContractError("isolated migration worker must return a JSON object")
    payload = cast(dict[str, object], decoded)
    measurement_value = payload.get("measurement")
    environment_value = payload.get("environment")
    if not isinstance(measurement_value, dict) or not isinstance(environment_value, dict):
        raise MethodContractError("isolated migration worker output is incomplete")
    return (
        _measurement_from_worker(cast(dict[str, object], measurement_value)),
        cast(dict[str, object], environment_value),
    )


def _optional_median(values: Sequence[int | None]) -> int | None:
    present = [value for value in values if value is not None]
    return round(statistics.median(present)) if present else None


def _aggregate_measurements(
    measurements: Sequence[MigrationMeasurement],
) -> MigrationMeasurement:
    if not measurements:
        raise RuntimeError("migration benchmark requires at least one timed measurement")
    first = measurements[0]
    for measurement in measurements[1:]:
        if (
            measurement.case_name != first.case_name
            or measurement.backend != first.backend
            or measurement.throughput_unit != first.throughput_unit
            or measurement.checksum != first.checksum
        ):
            raise RuntimeError("isolated migration measurements are not equivalent")
    timings = tuple(measurement.median_seconds for measurement in measurements)
    median_seconds = statistics.median(timings)
    work_items = statistics.median(
        measurement.throughput * measurement.median_seconds for measurement in measurements
    )
    peak_values = [
        measurement.process_peak_rss_bytes
        for measurement in measurements
        if measurement.process_peak_rss_bytes is not None
    ]
    return MigrationMeasurement(
        case_name=first.case_name,
        backend=first.backend,
        timings_seconds=timings,
        median_seconds=median_seconds,
        minimum_seconds=min(timings),
        maximum_seconds=max(timings),
        median_absolute_deviation_seconds=_median_absolute_deviation(timings),
        throughput=work_items / median_seconds,
        throughput_unit=first.throughput_unit,
        baseline_rss_bytes=_optional_median(
            [measurement.baseline_rss_bytes for measurement in measurements]
        ),
        process_peak_rss_bytes=max(peak_values) if peak_values else None,
        incremental_peak_rss_bytes=_optional_median(
            [measurement.incremental_peak_rss_bytes for measurement in measurements]
        ),
        python_traced_peak_bytes=max(
            measurement.python_traced_peak_bytes for measurement in measurements
        ),
        input_copy_bytes=_optional_median(
            [measurement.input_copy_bytes for measurement in measurements]
        ),
        output_copy_bytes=_optional_median(
            [measurement.output_copy_bytes for measurement in measurements]
        ),
        temporary_workspace_bytes=_optional_median(
            [measurement.temporary_workspace_bytes for measurement in measurements]
        ),
        result_projection_bytes=_optional_median(
            [measurement.result_projection_bytes for measurement in measurements]
        ),
        phase_seconds={
            "normalization": None,
            "input_copy": None,
            "kernel": None,
            "result_projection": None,
            "result_construction": None,
            "public_call_total": median_seconds,
        },
        checksum=first.checksum,
    )


def run_isolated_migration_benchmark(
    target: MigrationBenchmarkTarget,
    config: BenchmarkConfig,
    *,
    source_commit: str,
    run_url: str | None = None,
) -> MigrationBenchmarkArtifact:
    """Measure one reference/candidate pair in isolated fixed-thread subprocesses."""

    if not source_commit:
        raise MethodContractError("migration benchmark source_commit must be non-empty")
    single_run = replace(config, repetitions=1, warmups=0)
    for warmup in range(config.warmups):
        warmup_order = ("reference", "candidate") if warmup % 2 == 0 else ("candidate", "reference")
        for backend in warmup_order:
            if backend == "reference":
                _run_worker(target.reference_case, single_run, use_native=False)
            elif target.candidate_case is not None:
                _run_worker(target.candidate_case, single_run, use_native=True)

    reference_runs: list[MigrationMeasurement] = []
    candidate_runs: list[MigrationMeasurement] = []
    environment: Mapping[str, object] | None = None
    candidate_environment: Mapping[str, object] | None = None
    for repetition in range(config.repetitions):
        order = ("reference", "candidate") if repetition % 2 == 0 else ("candidate", "reference")
        for backend in order:
            if backend == "reference":
                measurement, measured_environment = _run_worker(
                    target.reference_case,
                    single_run,
                    use_native=False,
                )
                reference_runs.append(measurement)
                environment = environment or measured_environment
            elif target.candidate_case is not None:
                measurement, measured_environment = _run_worker(
                    target.candidate_case,
                    single_run,
                    use_native=True,
                )
                candidate_runs.append(measurement)
                candidate_environment = candidate_environment or measured_environment

    if environment is None:
        raise RuntimeError("reference migration benchmark did not run")
    reference = _aggregate_measurements(reference_runs)
    candidate = _aggregate_measurements(candidate_runs) if candidate_runs else None
    if candidate_environment is not None:
        for key in ("python", "platform", "machine", "polars", "numpy", "native_version"):
            if environment.get(key) != candidate_environment.get(key):
                raise RuntimeError(f"reference/candidate worker environment differs for {key}")
    admission = evaluate_admission(target, reference, candidate)
    return MigrationBenchmarkArtifact(
        target=target,
        config=config,
        reference=reference,
        candidate=candidate,
        admission=admission,
        generated_at=datetime.now(UTC),
        source_commit=source_commit,
        run_url=run_url,
        environment={
            **environment,
            "openblas_threads": 1,
            "mkl_threads": 1,
            "omp_threads": 1,
            "polars_threads": 2,
            "native_threads": 1,
            "isolation": "one child process per measured backend",
            "copy_measurement": "null until the selected boundary reports exact byte counters",
        },
    )


def validate_artifact(payload: Mapping[str, object]) -> None:
    """Reject malformed or incomplete migration sidecars in CI."""

    if payload.get("schema") != MIGRATION_BENCHMARK_SCHEMA:
        raise MethodContractError("unexpected migration benchmark schema")
    if payload.get("version") != MIGRATION_BENCHMARK_VERSION:
        raise MethodContractError("unsupported migration benchmark version")
    for name in (
        "generated_at",
        "source_commit",
        "target",
        "config",
        "environment",
        "reference",
        "admission",
    ):
        if payload.get(name) is None:
            raise MethodContractError(f"migration benchmark artifact is missing {name}")
    target = payload.get("target")
    config = payload.get("config")
    candidate = payload.get("candidate")
    admission = payload.get("admission")
    if (
        not isinstance(target, Mapping)
        or not isinstance(config, Mapping)
        or not isinstance(admission, Mapping)
    ):
        raise MethodContractError("migration target, config, and admission must be objects")
    state = admission.get("state")
    if state not in {
        "PROPOSED",
        "MEASURED",
        "ADMITTED",
        "SHIPPED_NATIVE",
        "OPTIMIZED_NON_NATIVE",
        "NOT_MIGRATING",
        "BLOCKED",
    }:
        raise MethodContractError("migration admission state is invalid")
    reasons = admission.get("reasons")
    if (
        not isinstance(reasons, list)
        or not reasons
        or not all(isinstance(reason, str) and reason for reason in reasons)
    ):
        raise MethodContractError("migration admission must contain non-empty reasons")
    if state == "ADMITTED":
        if candidate is None:
            raise MethodContractError("an admitted migration requires candidate measurements")
        if config.get("repetitions") != 7 or config.get("warmups") != 2:
            raise MethodContractError(
                "admission evidence requires seven repetitions and two warmups"
            )
    encoded = json.dumps(dict(payload), allow_nan=False, sort_keys=True)
    if not encoded:
        raise MethodContractError("migration benchmark artifact cannot be empty")


def _worker_payload(
    case_name: str, config: BenchmarkConfig, *, use_native: bool
) -> dict[str, object]:
    case, trace, environment = _run_benchmark_case_detailed(
        case_name,
        config,
        use_native=use_native,
    )
    return {
        "measurement": {
            "case_name": case.name,
            "backend": case.backend,
            "timings_seconds": list(trace.timings_seconds),
            "throughput": case.throughput,
            "throughput_unit": case.throughput_unit,
            "baseline_rss_bytes": trace.baseline_rss_bytes,
            "process_peak_rss_bytes": trace.process_peak_rss_bytes,
            "incremental_peak_rss_bytes": trace.incremental_peak_rss_bytes,
            "python_traced_peak_bytes": trace.python_traced_peak_bytes,
            "input_copy_bytes": None,
            "output_copy_bytes": None,
            "temporary_workspace_bytes": None,
            "result_projection_bytes": None,
            "checksum": case.checksum,
        },
        "environment": dict(environment),
    }


def _main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    worker = subparsers.add_parser("worker")
    worker.add_argument("--case", required=True)
    worker.add_argument("--config-json", required=True)
    worker.add_argument("--use-native", action="store_true")
    parsed = parser.parse_args(arguments)
    if parsed.command != "worker":  # pragma: no cover - argparse enforces this
        return 2
    decoded = json.loads(cast(str, parsed.config_json))
    if not isinstance(decoded, dict):
        raise MethodContractError("worker config must be a JSON object")
    config = _config_from_payload(cast(dict[str, object], decoded))
    payload = _worker_payload(
        cast(str, parsed.case),
        config,
        use_native=cast(bool, parsed.use_native),
    )
    sys.stdout.write(json.dumps(payload, allow_nan=False, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - subprocess worker
    raise SystemExit(_main())
