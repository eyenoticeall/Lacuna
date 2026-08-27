"""Private isolated benchmark and admission evidence for native migration work."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import os
import platform
import statistics
import subprocess
import sys
import time
import tracemalloc
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Literal, cast

import numpy as np
import numpy.typing as npt
import polars as pl

from lacuna._frames import frame_records
from lacuna.benchmark import (
    BenchmarkConfig,
    _current_rss_bytes,
    _instrument_migration_case,
    _process_peak_rss_bytes,
    _run_benchmark_case_detailed,
)
from lacuna.exceptions import MethodContractError
from lacuna.experiment import fingerprint
from lacuna.native import native_status

MIGRATION_BENCHMARK_SCHEMA = "lacuna.native-migration-benchmark"
MIGRATION_BENCHMARK_VERSION = 1
_PRIVATE_FINGERPRINT_CASES = {
    "migration.fingerprint.array.reference",
    "migration.fingerprint.array.streaming",
    "migration.fingerprint.frame.reference",
    "migration.fingerprint.frame.streaming",
}

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
    absolute_tolerance: float = 0.0
    relative_tolerance: float = 0.0

    def __post_init__(self) -> None:
        if not self.candidate_id or not self.public_operation or not self.reference_case:
            raise MethodContractError("migration benchmark target identifiers must be non-empty")
        for name, share in (
            ("public_latency_share", self.public_latency_share),
            ("public_rss_share", self.public_rss_share),
        ):
            if share is not None and (not math.isfinite(share) or not 0.0 <= share <= 1.0):
                raise MethodContractError(f"{name} must be a finite fraction in [0, 1]")
        for name, tolerance in (
            ("absolute_tolerance", self.absolute_tolerance),
            ("relative_tolerance", self.relative_tolerance),
        ):
            if not math.isfinite(tolerance) or tolerance < 0.0:
                raise MethodContractError(f"{name} must be finite and non-negative")
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
class MigrationCorrectness:
    """Exact-structure and tolerance-aware numerical comparison evidence."""

    match: bool
    exact_checksum_match: bool
    absolute_tolerance: float
    relative_tolerance: float
    numeric_values_compared: int
    maximum_absolute_error: float | None
    maximum_relative_error: float | None
    first_mismatch_path: str | None
    reason: str

    def to_dict(self) -> dict[str, object]:
        """Return finite JSON-compatible correctness evidence."""

        return {
            "match": self.match,
            "exact_checksum_match": self.exact_checksum_match,
            "absolute_tolerance": self.absolute_tolerance,
            "relative_tolerance": self.relative_tolerance,
            "numeric_values_compared": self.numeric_values_compared,
            "maximum_absolute_error": self.maximum_absolute_error,
            "maximum_relative_error": self.maximum_relative_error,
            "first_mismatch_path": self.first_mismatch_path,
            "reason": self.reason,
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
    correctness: MigrationCorrectness | None = None
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
                "absolute_tolerance": self.target.absolute_tolerance,
                "relative_tolerance": self.target.relative_tolerance,
            },
            "config": _config_payload(self.config),
            "environment": dict(self.environment),
            "reference": self.reference.to_dict(),
            "candidate": None if self.candidate is None else self.candidate.to_dict(),
            "correctness": None if self.correctness is None else self.correctness.to_dict(),
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

    phase_value = payload.get("phase_seconds")
    if phase_value is not None and not isinstance(phase_value, dict):
        raise MethodContractError("worker phase_seconds must be an object or null")
    phase_payload = cast(dict[str, object], phase_value or {})

    def optional_phase(name: str) -> float | None:
        value = phase_payload.get(name)
        if value is None:
            return None
        if not isinstance(value, int | float) or isinstance(value, bool):
            raise MethodContractError(f"worker phase {name} must be numeric or null")
        resolved = float(value)
        if not math.isfinite(resolved) or resolved < 0.0:
            raise MethodContractError(f"worker phase {name} must be finite and non-negative")
        return resolved

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
            "normalization": optional_phase("normalization"),
            "input_copy": optional_phase("input_copy"),
            "kernel": optional_phase("kernel"),
            "result_projection": optional_phase("result_projection"),
            "result_construction": optional_phase("result_construction"),
            "public_call_total": median_seconds,
        },
        checksum=string("checksum"),
    )


@dataclass(slots=True)
class _ComparisonStats:
    numeric_values_compared: int = 0
    maximum_absolute_error: float = 0.0
    maximum_relative_error: float = 0.0
    first_mismatch_path: str | None = None
    mismatch_reason: str | None = None


def _mapping_without_backend(value: Mapping[object, object]) -> dict[str, object]:
    normalized = {str(key): item for key, item in value.items() if str(key) != "backend"}
    if len(normalized) != sum(1 for key in value if str(key) != "backend"):
        raise MethodContractError("equivalence payload contains colliding stringified keys")
    return normalized


def _compare_equivalence_values(
    reference: object,
    candidate: object,
    *,
    path: str,
    absolute_tolerance: float,
    relative_tolerance: float,
    stats: _ComparisonStats,
) -> None:
    if stats.first_mismatch_path is not None:
        return
    if isinstance(reference, Mapping) and isinstance(candidate, Mapping):
        reference_mapping = _mapping_without_backend(reference)
        candidate_mapping = _mapping_without_backend(candidate)
        reference_keys = set(reference_mapping)
        candidate_keys = set(candidate_mapping)
        if reference_keys != candidate_keys:
            stats.first_mismatch_path = path
            missing = sorted(reference_keys - candidate_keys)
            unexpected = sorted(candidate_keys - reference_keys)
            stats.mismatch_reason = (
                f"mapping keys differ; missing={missing!r}, unexpected={unexpected!r}"
            )
            return
        for key in sorted(reference_keys):
            _compare_equivalence_values(
                reference_mapping[key],
                candidate_mapping[key],
                path=f"{path}.{key}",
                absolute_tolerance=absolute_tolerance,
                relative_tolerance=relative_tolerance,
                stats=stats,
            )
        return
    if isinstance(reference, list | tuple) and isinstance(candidate, list | tuple):
        if len(reference) != len(candidate):
            stats.first_mismatch_path = path
            stats.mismatch_reason = (
                f"sequence lengths differ; reference={len(reference)}, candidate={len(candidate)}"
            )
            return
        for index, (reference_item, candidate_item) in enumerate(
            zip(reference, candidate, strict=True)
        ):
            _compare_equivalence_values(
                reference_item,
                candidate_item,
                path=f"{path}[{index}]",
                absolute_tolerance=absolute_tolerance,
                relative_tolerance=relative_tolerance,
                stats=stats,
            )
        return
    if isinstance(reference, float) and isinstance(candidate, float):
        stats.numeric_values_compared += 1
        if not math.isfinite(reference) or not math.isfinite(candidate):
            stats.first_mismatch_path = path
            stats.mismatch_reason = "non-finite numerical evidence is not comparable"
            return
        absolute_error = abs(reference - candidate)
        scale = max(abs(reference), abs(candidate))
        relative_error = absolute_error / scale if scale else 0.0
        stats.maximum_absolute_error = max(stats.maximum_absolute_error, absolute_error)
        stats.maximum_relative_error = max(stats.maximum_relative_error, relative_error)
        if (
            reference == 0.0
            and candidate == 0.0
            and math.copysign(1.0, reference) != math.copysign(1.0, candidate)
        ):
            stats.first_mismatch_path = path
            stats.mismatch_reason = "signed-zero values differ"
            return
        if not math.isclose(
            reference,
            candidate,
            rel_tol=relative_tolerance,
            abs_tol=absolute_tolerance,
        ):
            stats.first_mismatch_path = path
            stats.mismatch_reason = (
                f"numerical values differ; reference={reference!r}, candidate={candidate!r}"
            )
        return
    if type(reference) is not type(candidate):
        stats.first_mismatch_path = path
        stats.mismatch_reason = (
            f"value types differ; reference={type(reference).__name__}, "
            f"candidate={type(candidate).__name__}"
        )
        return
    if reference != candidate:
        stats.first_mismatch_path = path
        stats.mismatch_reason = (
            f"structural values differ; reference={reference!r}, candidate={candidate!r}"
        )


def compare_equivalence_payloads(
    reference: Mapping[str, object],
    candidate: Mapping[str, object],
    *,
    reference_checksum: str,
    candidate_checksum: str,
    absolute_tolerance: float,
    relative_tolerance: float,
) -> MigrationCorrectness:
    """Compare complete evidence trees without weakening structural or checksum evidence."""

    for name, tolerance in (
        ("absolute_tolerance", absolute_tolerance),
        ("relative_tolerance", relative_tolerance),
    ):
        if not math.isfinite(tolerance) or tolerance < 0.0:
            raise MethodContractError(f"{name} must be finite and non-negative")
    stats = _ComparisonStats()
    _compare_equivalence_values(
        reference,
        candidate,
        path="root",
        absolute_tolerance=absolute_tolerance,
        relative_tolerance=relative_tolerance,
        stats=stats,
    )
    match = stats.first_mismatch_path is None
    exact_checksum_match = reference_checksum == candidate_checksum
    if match and stats.maximum_absolute_error == 0.0:
        reason = "complete evidence is structurally and numerically exact"
    elif match and exact_checksum_match:
        reason = (
            "structure is exact, every finite numerical value is within tolerance, and the "
            "normalized equivalence checksums match"
        )
    elif match:
        reason = (
            "structure is exact and every finite numerical value is within tolerance; normalized "
            "equivalence checksums differ"
        )
    else:
        reason = stats.mismatch_reason or "evidence differs"
    return MigrationCorrectness(
        match=match,
        exact_checksum_match=exact_checksum_match,
        absolute_tolerance=absolute_tolerance,
        relative_tolerance=relative_tolerance,
        numeric_values_compared=stats.numeric_values_compared,
        maximum_absolute_error=(
            stats.maximum_absolute_error if stats.numeric_values_compared else None
        ),
        maximum_relative_error=(
            stats.maximum_relative_error if stats.numeric_values_compared else None
        ),
        first_mismatch_path=stats.first_mismatch_path,
        reason=reason,
    )


def evaluate_admission(
    target: MigrationBenchmarkTarget,
    reference: MigrationMeasurement,
    candidate: MigrationMeasurement | None,
    *,
    correctness: MigrationCorrectness | None = None,
) -> MigrationAdmission:
    """Apply the mechanical materiality and v0.14 native admission thresholds."""

    material = (
        (target.public_latency_share or 0.0) >= 0.15
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

    correctness_match = (
        correctness.match if correctness is not None else reference.checksum == candidate.checksum
    )
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
        reason = "reference and candidate equivalence checksums differ"
        if correctness is not None:
            mismatch = (
                f" at {correctness.first_mismatch_path}"
                if correctness.first_mismatch_path is not None
                else ""
            )
            reason = f"reference and candidate evidence differ{mismatch}: {correctness.reason}"
        return MigrationAdmission(
            state="NOT_MIGRATING",
            material=material,
            correctness_match=False,
            throughput_ratio=throughput_ratio,
            rss_reduction_fraction=rss_reduction,
            latency_regression_fraction=latency_regression,
            reasons=(reason,),
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


def _worker_command(
    case_name: str,
    config: BenchmarkConfig,
    *,
    use_native: bool,
    instrumented: bool,
) -> list[str]:
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
    if instrumented:
        command.append("--instrumented")
    return command


def _run_worker(
    case_name: str,
    config: BenchmarkConfig,
    *,
    use_native: bool,
    instrumented: bool = False,
) -> tuple[MigrationMeasurement, Mapping[str, object], Mapping[str, object] | None]:
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
        _worker_command(
            case_name,
            config,
            use_native=use_native,
            instrumented=instrumented,
        ),
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
    equivalence_payload_value = payload.get("equivalence_payload")
    if not isinstance(measurement_value, dict) or not isinstance(environment_value, dict):
        raise MethodContractError("isolated migration worker output is incomplete")
    if equivalence_payload_value is not None and not isinstance(equivalence_payload_value, dict):
        raise MethodContractError("isolated migration equivalence payload must be an object")
    return (
        _measurement_from_worker(cast(dict[str, object], measurement_value)),
        cast(dict[str, object], environment_value),
        cast(dict[str, object], equivalence_payload_value)
        if equivalence_payload_value is not None
        else None,
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


def _add_instrumentation(
    measurement: MigrationMeasurement,
    instrumented: MigrationMeasurement,
) -> MigrationMeasurement:
    if (
        measurement.case_name != instrumented.case_name
        or measurement.backend != instrumented.backend
        or measurement.checksum != instrumented.checksum
    ):
        raise RuntimeError("instrumented migration result does not match the timed result")
    return replace(
        measurement,
        python_traced_peak_bytes=instrumented.python_traced_peak_bytes,
        input_copy_bytes=instrumented.input_copy_bytes,
        output_copy_bytes=instrumented.output_copy_bytes,
        temporary_workspace_bytes=instrumented.temporary_workspace_bytes,
        result_projection_bytes=instrumented.result_projection_bytes,
        phase_seconds={
            **instrumented.phase_seconds,
            "public_call_total": measurement.median_seconds,
        },
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
                measurement, measured_environment, _ = _run_worker(
                    target.reference_case,
                    single_run,
                    use_native=False,
                )
                reference_runs.append(measurement)
                environment = environment or measured_environment
            elif target.candidate_case is not None:
                measurement, measured_environment, _ = _run_worker(
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
    candidate_equivalence_payload: Mapping[str, object] | None = None
    (
        reference_instrumented,
        reference_instrumented_environment,
        reference_equivalence_payload,
    ) = _run_worker(
        target.reference_case,
        single_run,
        use_native=False,
        instrumented=True,
    )
    reference = _add_instrumentation(reference, reference_instrumented)
    if environment.get("python") != reference_instrumented_environment.get("python"):
        raise RuntimeError("reference instrumentation used a different Python runtime")
    if target.candidate_case is not None and candidate is not None:
        (
            candidate_instrumented,
            candidate_instrumented_environment,
            candidate_equivalence_payload,
        ) = _run_worker(
            target.candidate_case,
            single_run,
            use_native=True,
            instrumented=True,
        )
        candidate = _add_instrumentation(candidate, candidate_instrumented)
        if candidate_environment is not None and (
            candidate_environment.get("python") != candidate_instrumented_environment.get("python")
        ):
            raise RuntimeError("candidate instrumentation used a different Python runtime")
    if candidate_environment is not None:
        for key in ("python", "platform", "machine", "polars", "numpy", "native_version"):
            if environment.get(key) != candidate_environment.get(key):
                raise RuntimeError(f"reference/candidate worker environment differs for {key}")
    correctness: MigrationCorrectness | None = None
    if candidate is not None:
        if reference_equivalence_payload is None or candidate_equivalence_payload is None:
            raise RuntimeError("candidate admission requires complete equivalence payloads")
        correctness = compare_equivalence_payloads(
            reference_equivalence_payload,
            candidate_equivalence_payload,
            reference_checksum=reference.checksum,
            candidate_checksum=candidate.checksum,
            absolute_tolerance=target.absolute_tolerance,
            relative_tolerance=target.relative_tolerance,
        )
    admission = evaluate_admission(target, reference, candidate, correctness=correctness)
    return MigrationBenchmarkArtifact(
        target=target,
        config=config,
        reference=reference,
        candidate=candidate,
        admission=admission,
        generated_at=datetime.now(UTC),
        source_commit=source_commit,
        run_url=run_url,
        correctness=correctness,
        environment={
            **environment,
            "openblas_threads": 1,
            "mkl_threads": 1,
            "omp_threads": 1,
            "polars_threads": 2,
            "native_threads": 1,
            "isolation": "one child process per measured backend",
            "copy_measurement": (
                "exact logical boundary and compact-carrier bytes when candidate telemetry is "
                "available; null for uninstrumented backends"
            ),
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
    correctness = payload.get("correctness")
    admission = payload.get("admission")
    if (
        not isinstance(target, Mapping)
        or not isinstance(config, Mapping)
        or not isinstance(admission, Mapping)
    ):
        raise MethodContractError("migration target, config, and admission must be objects")
    for name in ("absolute_tolerance", "relative_tolerance"):
        value = target.get(name, 0.0)
        if (
            not isinstance(value, int | float)
            or isinstance(value, bool)
            or not math.isfinite(float(value))
            or float(value) < 0.0
        ):
            raise MethodContractError(f"migration target {name} must be finite and non-negative")
    if correctness is not None:
        if not isinstance(correctness, Mapping):
            raise MethodContractError("migration correctness must be an object or null")
        if not isinstance(correctness.get("match"), bool) or not isinstance(
            correctness.get("exact_checksum_match"), bool
        ):
            raise MethodContractError("migration correctness match fields must be booleans")
        count = correctness.get("numeric_values_compared")
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise MethodContractError(
                "migration correctness numeric_values_compared must be non-negative"
            )
        for name in (
            "absolute_tolerance",
            "relative_tolerance",
            "maximum_absolute_error",
            "maximum_relative_error",
        ):
            value = correctness.get(name)
            if value is None and name.startswith("maximum_"):
                continue
            if (
                not isinstance(value, int | float)
                or isinstance(value, bool)
                or not math.isfinite(float(value))
                or float(value) < 0.0
            ):
                raise MethodContractError(f"migration correctness {name} is invalid")
        if float(cast(int | float, correctness["absolute_tolerance"])) != float(
            cast(int | float, target.get("absolute_tolerance", 0.0))
        ) or float(cast(int | float, correctness["relative_tolerance"])) != float(
            cast(int | float, target.get("relative_tolerance", 0.0))
        ):
            raise MethodContractError("migration target and correctness tolerances differ")
        mismatch_path = correctness.get("first_mismatch_path")
        if mismatch_path is not None and not isinstance(mismatch_path, str):
            raise MethodContractError("migration correctness mismatch path must be text or null")
        reason = correctness.get("reason")
        if not isinstance(reason, str) or not reason:
            raise MethodContractError("migration correctness reason must be non-empty")
        if admission.get("correctness_match") is not correctness.get("match"):
            raise MethodContractError("migration correctness and admission outcomes differ")
        if candidate is not None:
            reference = payload.get("reference")
            if not isinstance(reference, Mapping) or not isinstance(candidate, Mapping):
                raise MethodContractError("migration correctness requires backend measurements")
            exact_checksum_match = reference.get("checksum") == candidate.get("checksum")
            if correctness.get("exact_checksum_match") is not exact_checksum_match:
                raise MethodContractError(
                    "migration correctness checksum outcome does not match measurements"
                )
        match = cast(bool, correctness["match"])
        if match and mismatch_path is not None:
            raise MethodContractError("matching migration correctness cannot have a mismatch path")
        if not match and not mismatch_path:
            raise MethodContractError("failed migration correctness requires a mismatch path")
        if count > 0 and (
            correctness.get("maximum_absolute_error") is None
            or correctness.get("maximum_relative_error") is None
        ):
            raise MethodContractError("numerical correctness requires maximum error evidence")
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
        if admission.get("correctness_match") is not True:
            raise MethodContractError("an admitted migration requires a correctness match")
        if correctness is None:
            reference = payload.get("reference")
            if not isinstance(reference, Mapping) or not isinstance(candidate, Mapping):
                raise MethodContractError("legacy admitted evidence requires measurements")
            if reference.get("checksum") != candidate.get("checksum"):
                raise MethodContractError(
                    "tolerance-aware admitted evidence requires a correctness record"
                )
    encoded = json.dumps(dict(payload), allow_nan=False, sort_keys=True)
    if not encoded:
        raise MethodContractError("migration benchmark artifact cannot be empty")


def _private_fingerprint_case(
    case_name: str,
    config: BenchmarkConfig,
    *,
    instrumented: bool,
) -> tuple[dict[str, object], dict[str, object], dict[str, object] | None]:
    """Measure full-call c14n-v1 paths without adding public benchmark-v6 cases."""

    row_count = config.rows
    operation: Callable[[], str]
    if ".array." in case_name:
        matrix: npt.NDArray[np.float64] = np.arange(row_count * 4, dtype=np.float64).reshape(
            row_count, 4
        )
        work_items = row_count * 4
        throughput_unit = "cells/second"
        if case_name.endswith(".reference"):
            operation = lambda: fingerprint(  # noqa: E731 - named benchmark operation
                matrix.tolist(),
                namespace="migration-fingerprint-array",
            )
            backend = "python_materialized_reference"
        else:
            operation = lambda: fingerprint(  # noqa: E731 - named benchmark operation
                matrix,
                namespace="migration-fingerprint-array",
            )
            backend = "python_streaming"
    else:
        frame = pl.DataFrame(
            {
                "time": np.arange(row_count, dtype=np.int64),
                "instrument": np.arange(row_count, dtype=np.int64) % config.instruments,
                "value": np.arange(row_count, dtype=np.float64) / 7.0,
                "group": np.where(np.arange(row_count) % 2 == 0, "A", "B"),
            }
        )
        work_items = row_count * frame.width
        throughput_unit = "cells/second"
        if case_name.endswith(".reference"):
            operation = lambda: fingerprint(  # noqa: E731 - named benchmark operation
                frame_records(frame),
                namespace="migration-fingerprint-frame",
            )
            backend = "python_materialized_reference"
        else:
            operation = lambda: fingerprint(  # noqa: E731 - named benchmark operation
                frame,
                namespace="migration-fingerprint-frame",
            )
            backend = "python_streaming"

    baseline_rss = _current_rss_bytes()
    baseline_peak = _process_peak_rss_bytes()
    for _ in range(config.warmups):
        operation()
    timings: list[float] = []
    outputs: set[str] = set()
    for _ in range(config.repetitions):
        gc.collect()
        started = time.perf_counter()
        output = operation()
        timings.append(time.perf_counter() - started)
        outputs.add(output)
    if len(outputs) != 1:
        raise RuntimeError(f"private migration case {case_name!r} was not deterministic")

    memory_output = next(iter(outputs))
    traced_peak = 0
    if instrumented:
        gc.collect()
        tracemalloc.start()
        memory_output = operation()
        _, traced_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        if memory_output not in outputs:
            raise RuntimeError(
                f"private migration case {case_name!r} changed during memory tracing"
            )
    process_peak = _process_peak_rss_bytes()
    incremental_peak = None
    if process_peak is not None:
        baseline = baseline_peak or baseline_rss
        if baseline is not None:
            incremental_peak = max(0, process_peak - baseline)
    median_seconds = statistics.median(timings)
    checksum = hashlib.sha256(memory_output.encode()).hexdigest()
    native = native_status()
    return (
        {
            "case_name": case_name,
            "backend": backend,
            "timings_seconds": timings,
            "throughput": work_items / median_seconds,
            "throughput_unit": throughput_unit,
            "baseline_rss_bytes": baseline_rss,
            "process_peak_rss_bytes": process_peak,
            "incremental_peak_rss_bytes": incremental_peak,
            "python_traced_peak_bytes": traced_peak,
            "input_copy_bytes": None,
            "output_copy_bytes": None,
            "temporary_workspace_bytes": None,
            "result_projection_bytes": None,
            "checksum": checksum,
        },
        {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor() or None,
            "polars": pl.__version__,
            "numpy": np.__version__,
            "native_available": native.available,
            "native_version": native.version,
            "process_peak_rss_bytes": process_peak,
            "memory_measurement": "tracemalloc plus process peak RSS",
            "timing_clock": "time.perf_counter",
            "checksum_normalization": "exact c14n-v1 digest identity",
        },
        {"fingerprint": memory_output} if instrumented else None,
    )


def _worker_payload(
    case_name: str,
    config: BenchmarkConfig,
    *,
    use_native: bool,
    instrumented: bool = True,
) -> dict[str, object]:
    if case_name in _PRIVATE_FINGERPRINT_CASES:
        measurement, private_environment, private_equivalence_payload = _private_fingerprint_case(
            case_name,
            config,
            instrumented=instrumented,
        )
        return {
            "measurement": measurement,
            "environment": private_environment,
            "equivalence_payload": private_equivalence_payload,
        }
    case, trace, public_environment, equivalence_payload = _run_benchmark_case_detailed(
        case_name,
        config,
        use_native=use_native,
        measure_python_memory=instrumented,
    )
    instrumentation = _instrument_migration_case(case_name, config) if instrumented else {}
    if instrumentation:
        if instrumentation.get("backend") != case.backend:
            raise RuntimeError("migration instrumentation selected a different backend")
        if instrumentation.get("checksum") != case.checksum:
            raise RuntimeError("migration instrumentation produced a different result")
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
            "input_copy_bytes": instrumentation.get("input_copy_bytes"),
            "output_copy_bytes": instrumentation.get("output_copy_bytes"),
            "temporary_workspace_bytes": instrumentation.get("temporary_workspace_bytes"),
            "result_projection_bytes": instrumentation.get("result_projection_bytes"),
            "phase_seconds": {
                "normalization": instrumentation.get("normalization"),
                "input_copy": instrumentation.get("input_copy"),
                "kernel": instrumentation.get("kernel"),
                "result_projection": instrumentation.get("result_projection"),
                "result_construction": instrumentation.get("result_construction"),
            },
            "checksum": case.checksum,
        },
        "environment": dict(public_environment),
        "equivalence_payload": equivalence_payload if instrumented else None,
    }


def _main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    worker = subparsers.add_parser("worker")
    worker.add_argument("--case", required=True)
    worker.add_argument("--config-json", required=True)
    worker.add_argument("--use-native", action="store_true")
    worker.add_argument("--instrumented", action="store_true")
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
        instrumented=cast(bool, parsed.instrumented),
    )
    sys.stdout.write(json.dumps(payload, allow_nan=False, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - subprocess worker
    raise SystemExit(_main())
