"""Deterministic parameter, temporal, and universe robustness evidence."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from numbers import Real
from typing import Literal, TypeAlias

import numpy as np

from lacuna.exceptions import DataContractError, MethodContractError
from lacuna.experiment import AttemptStatus, ExperimentRegistry, fingerprint
from lacuna.types import AnalysisResult, Finding, FindingState, JsonValue, ResultMetadata, Severity

Distribution: TypeAlias = Literal["normal", "lognormal", "uniform"]
FailurePolicy: TypeAlias = Literal["record", "raise"]
ObjectiveDirection: TypeAlias = Literal["maximize", "minimize"]
TemporalValue: TypeAlias = date | datetime


def _trimmed(value: str, *, name: str) -> str:
    if not value or value.strip() != value:
        raise MethodContractError(f"{name} must be a non-empty trimmed string")
    return value


def _finite_metric(result: AnalysisResult, name: str) -> float:
    observed = result.metrics.get(name)
    if not isinstance(observed, Real) or isinstance(observed, bool):
        raise DataContractError(f"metric {name!r} must be a finite numeric scalar")
    value = float(observed)
    if not math.isfinite(value):
        raise DataContractError(f"metric {name!r} must be a finite numeric scalar")
    return value


def _optional_metric(result: AnalysisResult, name: str | None) -> float | None:
    return _finite_metric(result, name) if name is not None else None


def _validate_analysis_configuration(
    *,
    objective: str,
    evaluator_name: str,
    code_id: str,
    evaluator_version: int,
    direction: ObjectiveDirection,
    failure_policy: FailurePolicy,
) -> None:
    _trimmed(objective, name="objective")
    _trimmed(evaluator_name, name="evaluator_name")
    _trimmed(code_id, name="code_id")
    if evaluator_version < 1:
        raise MethodContractError("evaluator_version must be positive")
    if direction not in {"maximize", "minimize"}:
        raise MethodContractError("direction must be 'maximize' or 'minimize'")
    if failure_policy not in {"record", "raise"}:
        raise MethodContractError("failure_policy must be 'record' or 'raise'")


@dataclass(frozen=True, slots=True)
class PerturbationSpec:
    """One numeric perturbation distribution around a selected value."""

    distribution: Distribution = "normal"
    scale: float = 0.1
    lower: float | None = None
    upper: float | None = None
    integer: bool = False

    def __post_init__(self) -> None:
        if self.distribution not in {"normal", "lognormal", "uniform"}:
            raise MethodContractError("distribution must be normal, lognormal, or uniform")
        if not math.isfinite(self.scale) or self.scale <= 0.0:
            raise MethodContractError("perturbation scale must be positive and finite")
        if self.lower is not None and not math.isfinite(self.lower):
            raise MethodContractError("perturbation lower bound must be finite")
        if self.upper is not None and not math.isfinite(self.upper):
            raise MethodContractError("perturbation upper bound must be finite")
        if self.lower is not None and self.upper is not None and self.lower > self.upper:
            raise MethodContractError("perturbation lower bound must not exceed upper bound")

    def to_parameters(self) -> dict[str, JsonValue]:
        return {
            "distribution": self.distribution,
            "scale": self.scale,
            "lower": self.lower,
            "upper": self.upper,
            "integer": self.integer,
        }


def _sample_parameter(
    rng: np.random.Generator,
    *,
    center: float,
    spec: PerturbationSpec,
) -> float | int | None:
    if spec.distribution == "normal":
        value = center + float(rng.normal(0.0, spec.scale))
    elif spec.distribution == "lognormal":
        if center <= 0.0:
            raise MethodContractError("lognormal perturbations require a positive selected value")
        value = center * math.exp(float(rng.normal(0.0, spec.scale)))
    else:
        value = center + float(rng.uniform(-spec.scale, spec.scale))
    if spec.integer:
        value = float(np.rint(value))
    if spec.lower is not None and value < spec.lower:
        return None
    if spec.upper is not None and value > spec.upper:
        return None
    return int(value) if spec.integer else value


def continuous_perturbation(
    evaluate: Callable[[Mapping[str, JsonValue]], AnalysisResult],
    *,
    selected_parameters: Mapping[str, JsonValue],
    perturbations: Mapping[str, PerturbationSpec],
    objective: str,
    evaluator_name: str,
    sample_id: str,
    code_id: str,
    draws: int = 500,
    seed: int = 0,
    evaluator_version: int = 1,
    direction: ObjectiveDirection = "maximize",
    constraint: Callable[[Mapping[str, JsonValue]], bool] | None = None,
    constraint_name: str | None = None,
    failure_policy: FailurePolicy = "record",
    max_attempts: int | None = None,
    evidence_threshold: float | None = None,
    registry: ExperimentRegistry | None = None,
) -> AnalysisResult:
    """Sample deterministic local perturbations and preserve rejection/evaluation failures."""

    if not callable(evaluate):
        raise MethodContractError("evaluate must be callable")
    _validate_analysis_configuration(
        objective=objective,
        evaluator_name=evaluator_name,
        code_id=code_id,
        evaluator_version=evaluator_version,
        direction=direction,
        failure_policy=failure_policy,
    )
    _trimmed(sample_id, name="sample_id")
    if draws < 1:
        raise MethodContractError("draws must be positive")
    if seed < 0:
        raise MethodContractError("seed must be non-negative")
    if not perturbations:
        raise MethodContractError("perturbations must contain at least one parameter")
    if constraint is not None and not callable(constraint):
        raise MethodContractError("constraint must be callable")
    if (constraint is None) != (constraint_name is None):
        raise MethodContractError("constraint and constraint_name must be provided together")
    if constraint_name is not None:
        _trimmed(constraint_name, name="constraint_name")
    resolved_max_attempts = max_attempts if max_attempts is not None else draws * 100
    if resolved_max_attempts < draws:
        raise MethodContractError("max_attempts must be at least draws")
    if evidence_threshold is not None and not math.isfinite(evidence_threshold):
        raise MethodContractError("evidence_threshold must be finite when provided")

    centers: dict[str, float] = {}
    for name, spec in perturbations.items():
        _trimmed(name, name="perturbation parameter")
        if not isinstance(spec, PerturbationSpec):
            raise MethodContractError("perturbation values must be PerturbationSpec instances")
        raw_center = selected_parameters.get(name)
        if not isinstance(raw_center, Real) or isinstance(raw_center, bool):
            raise DataContractError(f"selected parameter {name!r} must be finite and numeric")
        center = float(raw_center)
        if not math.isfinite(center):
            raise DataContractError(f"selected parameter {name!r} must be finite and numeric")
        if spec.distribution == "lognormal" and center <= 0.0:
            raise MethodContractError("lognormal perturbations require positive selected values")
        centers[name] = center

    rng = np.random.default_rng(seed)
    rows: list[dict[str, JsonValue]] = []
    accepted = 0
    attempted = 0
    rejections: Counter[str] = Counter()
    objectives: list[float] = []
    ordered_names = tuple(sorted(perturbations))
    while accepted < draws and attempted < resolved_max_attempts:
        attempted += 1
        parameters = dict(selected_parameters)
        rejected = False
        for name in ordered_names:
            sampled = _sample_parameter(
                rng,
                center=centers[name],
                spec=perturbations[name],
            )
            if sampled is None:
                rejections["bounds"] += 1
                rejected = True
                break
            parameters[name] = sampled
        if rejected:
            continue
        if constraint is not None:
            try:
                constraint_passed = constraint(parameters)
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception:
                rejections["constraint_error"] += 1
                continue
            if not isinstance(constraint_passed, bool):
                raise DataContractError("constraint must return bool")
            if not constraint_passed:
                rejections["constraint"] += 1
                continue

        accepted += 1
        sample_number = accepted
        sample_fingerprint = fingerprint(parameters, namespace="continuous-perturbation-point")
        try:
            result = evaluate(parameters)
            if not isinstance(result, AnalysisResult):
                raise DataContractError("evaluate must return an AnalysisResult")
            value = _finite_metric(result, objective)
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as error:
            if failure_policy == "raise":
                raise
            category = type(error).__name__
            rows.append(
                {
                    **parameters,
                    "sample": sample_number,
                    "point_id": sample_fingerprint,
                    "status": "failed",
                    "objective": None,
                    "error_category": category,
                }
            )
            if registry is not None:
                registry.record(
                    parameters=parameters,
                    status=AttemptStatus.FAILED,
                    error_category=category,
                    method=evaluator_name,
                    method_version=evaluator_version,
                    data_fingerprint=sample_id,
                    code_fingerprint=code_id,
                    metadata={"perturbation_sample": sample_number, "seed": seed},
                )
            continue
        objectives.append(value)
        rows.append(
            {
                **parameters,
                "sample": sample_number,
                "point_id": sample_fingerprint,
                "status": "completed",
                "objective": value,
                "error_category": None,
            }
        )
        if registry is not None:
            registry.record(
                parameters=parameters,
                metric=value,
                metric_name=objective,
                method=evaluator_name,
                method_version=evaluator_version,
                data_fingerprint=sample_id,
                code_fingerprint=code_id,
                result_fingerprint=result.metadata.input_fingerprint,
                metadata={"perturbation_sample": sample_number, "seed": seed},
            )

    findings: list[Finding] = []
    if accepted < draws:
        findings.append(
            Finding(
                code="PERTURBATION_ACCEPTANCE_SHORTFALL",
                title="Perturbation sampler exhausted its attempt budget",
                message="The requested accepted perturbation count was not reached.",
                state=FindingState.FAIL,
                severity=Severity.HIGH,
                category="robustness",
                evidence={"requested": draws, "accepted": accepted, "attempted": attempted},
            )
        )
    rejected_count = attempted - accepted
    rejection_rate = rejected_count / attempted if attempted else 0.0
    if rejection_rate > 0.5:
        findings.append(
            Finding(
                code="PERTURBATION_HIGH_REJECTION_RATE",
                title="Perturbation constraints reject most samples",
                message="Local evidence may represent a narrow feasible region.",
                state=FindingState.WARN,
                severity=Severity.MEDIUM,
                category="robustness",
                evidence={"rejection_rate": rejection_rate},
            )
        )
    failed_evaluations = accepted - len(objectives)
    if failed_evaluations:
        findings.append(
            Finding(
                code="PERTURBATION_EVALUATION_FAILURES",
                title="Accepted perturbations include evaluation failures",
                message="Failed evaluations remain visible in the perturbation distribution.",
                state=FindingState.WARN,
                severity=Severity.MEDIUM,
                category="robustness",
                evidence={"failed_evaluations": failed_evaluations, "accepted": accepted},
            )
        )
    findings.append(
        Finding(
            code="PERTURBATION_REPRODUCIBLE",
            title="Perturbation generator is reproducible",
            message="The seed, distributions, bounds, and constraint identity are recorded.",
            state=FindingState.PASS,
            severity=Severity.INFO,
            category="reproducibility",
            evidence={"seed": seed, "attempted": attempted},
        )
    )

    median = float(np.median(objectives)) if objectives else None
    dispersion = float(np.std(objectives, ddof=1)) if len(objectives) > 1 else None
    positive_fraction = (
        sum(value > 0.0 for value in objectives) / len(objectives) if objectives else None
    )
    passing_fraction = None
    if objectives and evidence_threshold is not None:
        passing_fraction = sum(
            (
                value >= evidence_threshold
                if direction == "maximize"
                else value <= evidence_threshold
            )
            for value in objectives
        ) / len(objectives)
    rejection_rows: tuple[dict[str, JsonValue], ...] = tuple(
        {"reason": reason, "count": count, "fraction_of_attempts": count / attempted}
        for reason, count in sorted(rejections.items())
    )
    specs = {name: perturbations[name].to_parameters() for name in ordered_names}
    input_fingerprint = fingerprint(
        {
            "selected_parameters": selected_parameters,
            "perturbations": specs,
            "objective": objective,
            "evaluator_name": evaluator_name,
            "evaluator_version": evaluator_version,
            "sample_id": sample_id,
            "code_id": code_id,
            "draws": draws,
            "seed": seed,
            "constraint_name": constraint_name,
        },
        namespace="continuous-perturbation-input",
    )
    return AnalysisResult(
        metadata=ResultMetadata(
            method="robustness.continuous_perturbation",
            method_version=1,
            parameters={
                "objective": objective,
                "direction": direction,
                "evaluator_name": evaluator_name,
                "evaluator_version": evaluator_version,
                "sample_id": sample_id,
                "code_id": code_id,
                "draws": draws,
                "seed": seed,
                "max_attempts": resolved_max_attempts,
                "constraint_name": constraint_name,
                "failure_policy": failure_policy,
                "perturbations": specs,
                "evidence_threshold": evidence_threshold,
            },
            seed=seed,
            input_fingerprint=input_fingerprint,
        ),
        metrics={
            "requested_draws": draws,
            "attempted_samples": attempted,
            "accepted_samples": accepted,
            "successful_evaluations": len(objectives),
            "failed_evaluations": failed_evaluations,
            "rejected_samples": rejected_count,
            "rejection_rate": rejection_rate,
            "objective_median": median,
            "objective_dispersion": dispersion,
            "positive_fraction": positive_fraction,
            "passing_fraction": passing_fraction,
        },
        findings=tuple(findings),
        tables={"perturbations": tuple(rows), "rejections": rejection_rows},
        warnings=("Perturbation evidence is local to the declared distributions and constraints.",),
    )


def _validate_temporal(value: TemporalValue, *, name: str) -> None:
    if isinstance(value, datetime) and (value.tzinfo is None or value.utcoffset() is None):
        raise MethodContractError(f"{name} datetime must be timezone-aware")


def _temporal_text(value: TemporalValue) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return value.isoformat()


@dataclass(frozen=True, slots=True)
class Subperiod:
    """A declared half-open evaluation window with a stable sample identity."""

    name: str
    start: TemporalValue
    end: TemporalValue
    sample_id: str

    def __post_init__(self) -> None:
        _trimmed(self.name, name="subperiod name")
        _trimmed(self.sample_id, name="subperiod sample_id")
        _validate_temporal(self.start, name="subperiod start")
        _validate_temporal(self.end, name="subperiod end")
        if type(self.start) is not type(self.end):
            raise MethodContractError("subperiod start and end must use the same temporal type")
        if self.start >= self.end:
            raise MethodContractError("subperiod windows must satisfy start < end")

    def to_parameters(self) -> dict[str, JsonValue]:
        return {
            "name": self.name,
            "start": _temporal_text(self.start),
            "end": _temporal_text(self.end),
            "sample_id": self.sample_id,
        }


def _overlapping_periods(periods: Sequence[Subperiod]) -> tuple[tuple[str, str], ...]:
    overlaps: list[tuple[str, str]] = []
    for position, left in enumerate(periods):
        for right in periods[position + 1 :]:
            if type(left.start) is not type(right.start):
                raise MethodContractError("all subperiods must use the same temporal type")
            if left.start < right.end and right.start < left.end:
                overlaps.append((left.name, right.name))
    return tuple(overlaps)


def subperiod_analysis(
    evaluate: Callable[[Subperiod], AnalysisResult],
    *,
    periods: Sequence[Subperiod],
    objective: str,
    sample_count_metric: str,
    evaluator_name: str,
    code_id: str,
    outcome_metric: str | None = None,
    confidence_lower_metric: str | None = None,
    confidence_upper_metric: str | None = None,
    evaluator_version: int = 1,
    direction: ObjectiveDirection = "maximize",
    failure_policy: FailurePolicy = "record",
    concentration_threshold: float = 0.6,
    registry: ExperimentRegistry | None = None,
) -> AnalysisResult:
    """Evaluate declared windows and quantify sign, trend, failure, and outcome concentration."""

    if not callable(evaluate):
        raise MethodContractError("evaluate must be callable")
    _validate_analysis_configuration(
        objective=objective,
        evaluator_name=evaluator_name,
        code_id=code_id,
        evaluator_version=evaluator_version,
        direction=direction,
        failure_policy=failure_policy,
    )
    _trimmed(sample_count_metric, name="sample_count_metric")
    for name, label in [
        (outcome_metric, "outcome_metric"),
        (confidence_lower_metric, "confidence_lower_metric"),
        (confidence_upper_metric, "confidence_upper_metric"),
    ]:
        if name is not None:
            _trimmed(name, name=label)
    if (confidence_lower_metric is None) != (confidence_upper_metric is None):
        raise MethodContractError("both confidence interval metric names must be provided together")
    if not math.isfinite(concentration_threshold) or not 0.0 < concentration_threshold <= 1.0:
        raise MethodContractError("concentration_threshold must be in (0, 1]")
    if not periods:
        raise MethodContractError("periods must contain at least one Subperiod")
    if any(not isinstance(period, Subperiod) for period in periods):
        raise MethodContractError("periods must contain Subperiod instances")
    names = [period.name for period in periods]
    if len(names) != len(set(names)):
        raise MethodContractError("subperiod names must be unique")
    sample_ids = [period.sample_id for period in periods]
    if len(sample_ids) != len(set(sample_ids)):
        raise MethodContractError("subperiod sample_ids must be unique")
    overlaps = _overlapping_periods(periods)

    rows: list[dict[str, JsonValue]] = []
    objectives: list[float] = []
    successful_positions: list[int] = []
    outcomes: list[float] = []
    failed = 0
    for position, period in enumerate(periods):
        parameters = period.to_parameters()
        try:
            result = evaluate(period)
            if not isinstance(result, AnalysisResult):
                raise DataContractError("evaluate must return an AnalysisResult")
            value = _finite_metric(result, objective)
            count_value = _finite_metric(result, sample_count_metric)
            if count_value < 0.0 or not count_value.is_integer():
                raise DataContractError("sample-count metric must be a non-negative integer")
            outcome = _optional_metric(result, outcome_metric)
            confidence_lower = _optional_metric(result, confidence_lower_metric)
            confidence_upper = _optional_metric(result, confidence_upper_metric)
            if (
                confidence_lower is not None
                and confidence_upper is not None
                and confidence_lower > confidence_upper
            ):
                raise DataContractError("confidence interval lower metric exceeds upper metric")
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as error:
            if failure_policy == "raise":
                raise
            category = type(error).__name__
            failed += 1
            rows.append(
                {
                    **parameters,
                    "status": "failed",
                    "objective": None,
                    "sample_count": None,
                    "outcome": None,
                    "confidence_lower": None,
                    "confidence_upper": None,
                    "error_category": category,
                }
            )
            if registry is not None:
                registry.record(
                    parameters=parameters,
                    status=AttemptStatus.FAILED,
                    error_category=category,
                    method=evaluator_name,
                    method_version=evaluator_version,
                    data_fingerprint=period.sample_id,
                    code_fingerprint=code_id,
                    metadata={"robustness_axis": "subperiod"},
                )
            continue
        objectives.append(value)
        successful_positions.append(position)
        if outcome is not None:
            outcomes.append(outcome)
        rows.append(
            {
                **parameters,
                "status": "completed",
                "objective": value,
                "sample_count": int(count_value),
                "outcome": outcome,
                "confidence_lower": confidence_lower,
                "confidence_upper": confidence_upper,
                "error_category": None,
            }
        )
        if registry is not None:
            registry.record(
                parameters=parameters,
                metric=value,
                metric_name=objective,
                method=evaluator_name,
                method_version=evaluator_version,
                data_fingerprint=period.sample_id,
                code_fingerprint=code_id,
                result_fingerprint=result.metadata.input_fingerprint,
                metadata={"robustness_axis": "subperiod"},
            )

    findings: list[Finding] = []
    if failed:
        findings.append(
            Finding(
                code="SUBPERIOD_EVALUATION_FAILURES",
                title="Subperiod evidence contains failed windows",
                message="Failed or undefined windows remain visible in the period table.",
                state=FindingState.WARN,
                severity=Severity.MEDIUM,
                category="robustness",
                evidence={"failed_periods": failed, "period_count": len(periods)},
            )
        )
    if overlaps:
        findings.append(
            Finding(
                code="SUBPERIOD_OVERLAP",
                title="Declared subperiods overlap",
                message=(
                    "Period-level evidence is dependent and must not be interpreted as independent."
                ),
                state=FindingState.WARN,
                severity=Severity.MEDIUM,
                category="robustness",
                evidence={"overlaps": overlaps},
            )
        )

    positive_fraction = (
        sum(value > 0.0 for value in objectives) / len(objectives) if objectives else None
    )
    sign_consistency = None
    if objectives:
        sign_counts = Counter(
            1 if value > 0.0 else -1 if value < 0.0 else 0 for value in objectives
        )
        sign_consistency = max(sign_counts.values()) / len(objectives)
        if sign_consistency < 0.8:
            findings.append(
                Finding(
                    code="SUBPERIOD_SIGN_INSTABILITY",
                    title="Objective sign is unstable across subperiods",
                    message="Successful windows do not show a consistent objective direction.",
                    state=FindingState.WARN,
                    severity=Severity.HIGH,
                    category="robustness",
                    evidence={"sign_consistency": sign_consistency},
                )
            )
        else:
            findings.append(
                Finding(
                    code="SUBPERIOD_SIGN_CONSISTENCY",
                    title="Objective sign is consistent across subperiods",
                    message="At least 80% of successful windows share the same objective sign.",
                    state=FindingState.PASS,
                    severity=Severity.INFO,
                    category="robustness",
                    evidence={"sign_consistency": sign_consistency},
                )
            )

    top_absolute_outcome_share = None
    if outcomes:
        absolute_total = sum(abs(value) for value in outcomes)
        if absolute_total > 0.0:
            top_absolute_outcome_share = max(abs(value) for value in outcomes) / absolute_total
            if top_absolute_outcome_share >= concentration_threshold:
                findings.append(
                    Finding(
                        code="SUBPERIOD_OUTCOME_CONCENTRATION",
                        title="Outcome is concentrated in one subperiod",
                        message="One window supplies a large share of absolute total outcome.",
                        state=FindingState.WARN,
                        severity=Severity.HIGH,
                        category="robustness",
                        evidence={
                            "top_absolute_outcome_share": top_absolute_outcome_share,
                            "threshold": concentration_threshold,
                        },
                    )
                )

    trend = None
    if len(objectives) > 1:
        trend = float(np.polyfit(successful_positions, objectives, 1)[0])
    worst = None
    best = None
    if objectives:
        worst = min(objectives) if direction == "maximize" else max(objectives)
        best = max(objectives) if direction == "maximize" else min(objectives)
    input_fingerprint = fingerprint(
        {
            "periods": tuple(period.to_parameters() for period in periods),
            "objective": objective,
            "sample_count_metric": sample_count_metric,
            "outcome_metric": outcome_metric,
            "evaluator_name": evaluator_name,
            "evaluator_version": evaluator_version,
            "code_id": code_id,
        },
        namespace="subperiod-analysis-input",
    )
    return AnalysisResult(
        metadata=ResultMetadata(
            method="robustness.subperiod_analysis",
            method_version=1,
            parameters={
                "objective": objective,
                "direction": direction,
                "sample_count_metric": sample_count_metric,
                "outcome_metric": outcome_metric,
                "confidence_lower_metric": confidence_lower_metric,
                "confidence_upper_metric": confidence_upper_metric,
                "evaluator_name": evaluator_name,
                "evaluator_version": evaluator_version,
                "code_id": code_id,
                "failure_policy": failure_policy,
                "concentration_threshold": concentration_threshold,
            },
            input_fingerprint=input_fingerprint,
        ),
        metrics={
            "period_count": len(periods),
            "successful_periods": len(objectives),
            "failed_periods": failed,
            "overlap_count": len(overlaps),
            "positive_fraction": positive_fraction,
            "sign_consistency": sign_consistency,
            "worst_objective": worst,
            "best_objective": best,
            "objective_dispersion": (
                float(np.std(objectives, ddof=1)) if len(objectives) > 1 else None
            ),
            "objective_trend_per_period": trend,
            "top_absolute_outcome_share": top_absolute_outcome_share,
        },
        findings=tuple(findings),
        tables={"subperiods": tuple(rows)},
        warnings=(
            "Subperiod results are conditional on the declared windows and evaluator semantics.",
        ),
    )


@dataclass(frozen=True, slots=True)
class UniverseScenario:
    """A timestamped, reproducible eligibility set for universe robustness."""

    name: str
    membership_id: str
    as_of: TemporalValue
    instrument_ids: tuple[str, ...]
    definition: str
    point_in_time: bool = True

    def __post_init__(self) -> None:
        _trimmed(self.name, name="universe name")
        _trimmed(self.membership_id, name="membership_id")
        _trimmed(self.definition, name="universe definition")
        _validate_temporal(self.as_of, name="universe as_of")
        if not self.instrument_ids:
            raise MethodContractError("universe instrument_ids must not be empty")
        if any(
            not identifier or identifier.strip() != identifier for identifier in self.instrument_ids
        ):
            raise MethodContractError("universe instrument_ids must be non-empty trimmed strings")
        if len(self.instrument_ids) != len(set(self.instrument_ids)):
            raise MethodContractError("universe instrument_ids must be unique")

    def to_parameters(self) -> dict[str, JsonValue]:
        return {
            "name": self.name,
            "membership_id": self.membership_id,
            "as_of": _temporal_text(self.as_of),
            "instrument_ids": tuple(sorted(self.instrument_ids)),
            "definition": self.definition,
            "point_in_time": self.point_in_time,
        }


def universe_perturbation(
    evaluate: Callable[[UniverseScenario], AnalysisResult],
    *,
    universes: Sequence[UniverseScenario],
    baseline: str,
    objective: str,
    sample_count_metric: str,
    evaluator_name: str,
    code_id: str,
    evaluator_version: int = 1,
    direction: ObjectiveDirection = "maximize",
    failure_policy: FailurePolicy = "record",
    registry: ExperimentRegistry | None = None,
) -> AnalysisResult:
    """Evaluate timestamped eligibility sets with retained-sample and composition evidence."""

    if not callable(evaluate):
        raise MethodContractError("evaluate must be callable")
    _validate_analysis_configuration(
        objective=objective,
        evaluator_name=evaluator_name,
        code_id=code_id,
        evaluator_version=evaluator_version,
        direction=direction,
        failure_policy=failure_policy,
    )
    _trimmed(sample_count_metric, name="sample_count_metric")
    _trimmed(baseline, name="baseline")
    if not universes:
        raise MethodContractError("universes must contain at least one UniverseScenario")
    if any(not isinstance(universe, UniverseScenario) for universe in universes):
        raise MethodContractError("universes must contain UniverseScenario instances")
    names = [universe.name for universe in universes]
    if len(names) != len(set(names)):
        raise MethodContractError("universe names must be unique")
    memberships = [universe.membership_id for universe in universes]
    if len(memberships) != len(set(memberships)):
        raise MethodContractError("universe membership_ids must be unique")
    try:
        baseline_universe = next(universe for universe in universes if universe.name == baseline)
    except StopIteration as error:
        raise MethodContractError("baseline must identify a declared universe") from error

    baseline_ids = set(baseline_universe.instrument_ids)
    rows: list[dict[str, JsonValue]] = []
    objectives: list[float] = []
    failed = 0
    min_jaccard = 1.0
    for universe in universes:
        parameters = universe.to_parameters()
        instrument_ids = set(universe.instrument_ids)
        intersection = len(baseline_ids.intersection(instrument_ids))
        union = len(baseline_ids.union(instrument_ids))
        jaccard = intersection / union
        retained_fraction = intersection / len(baseline_ids)
        min_jaccard = min(min_jaccard, jaccard)
        composition: dict[str, JsonValue] = {
            "instrument_count": len(instrument_ids),
            "retained_baseline_instruments": intersection,
            "retained_baseline_fraction": retained_fraction,
            "composition_jaccard": jaccard,
            "added_instruments": len(instrument_ids.difference(baseline_ids)),
            "removed_instruments": len(baseline_ids.difference(instrument_ids)),
        }
        try:
            result = evaluate(universe)
            if not isinstance(result, AnalysisResult):
                raise DataContractError("evaluate must return an AnalysisResult")
            value = _finite_metric(result, objective)
            count_value = _finite_metric(result, sample_count_metric)
            if count_value < 0.0 or not count_value.is_integer():
                raise DataContractError("sample-count metric must be a non-negative integer")
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as error:
            if failure_policy == "raise":
                raise
            category = type(error).__name__
            failed += 1
            rows.append(
                {
                    **parameters,
                    **composition,
                    "status": "failed",
                    "objective": None,
                    "sample_count": None,
                    "error_category": category,
                }
            )
            if registry is not None:
                registry.record(
                    parameters=parameters,
                    status=AttemptStatus.FAILED,
                    error_category=category,
                    method=evaluator_name,
                    method_version=evaluator_version,
                    data_fingerprint=universe.membership_id,
                    code_fingerprint=code_id,
                    metadata={"robustness_axis": "universe"},
                )
            continue
        objectives.append(value)
        rows.append(
            {
                **parameters,
                **composition,
                "status": "completed",
                "objective": value,
                "sample_count": int(count_value),
                "error_category": None,
            }
        )
        if registry is not None:
            registry.record(
                parameters=parameters,
                metric=value,
                metric_name=objective,
                method=evaluator_name,
                method_version=evaluator_version,
                data_fingerprint=universe.membership_id,
                code_fingerprint=code_id,
                result_fingerprint=result.metadata.input_fingerprint,
                metadata={"robustness_axis": "universe"},
            )

    findings: list[Finding] = []
    retrospective = [universe.name for universe in universes if not universe.point_in_time]
    if retrospective:
        findings.append(
            Finding(
                code="UNIVERSE_RETROSPECTIVE_MEMBERSHIP",
                title="Universe evidence includes retrospective membership",
                message="Current or retrospective membership is not survivorship-safe evidence.",
                state=FindingState.WARN,
                severity=Severity.HIGH,
                category="bias",
                evidence={"universes": tuple(retrospective)},
            )
        )
    else:
        findings.append(
            Finding(
                code="UNIVERSE_POINT_IN_TIME_DECLARED",
                title="All universe scenarios declare point-in-time membership",
                message=(
                    "Membership identity and eligibility timestamp are recorded for every scenario."
                ),
                state=FindingState.PASS,
                severity=Severity.INFO,
                category="bias",
            )
        )
    if failed:
        findings.append(
            Finding(
                code="UNIVERSE_EVALUATION_FAILURES",
                title="Universe evidence contains failed scenarios",
                message="Failed or undefined universes remain visible in the scenario table.",
                state=FindingState.WARN,
                severity=Severity.MEDIUM,
                category="robustness",
                evidence={"failed_universes": failed, "universe_count": len(universes)},
            )
        )

    worst = None
    best = None
    if objectives:
        worst = min(objectives) if direction == "maximize" else max(objectives)
        best = max(objectives) if direction == "maximize" else min(objectives)
    input_fingerprint = fingerprint(
        {
            "universes": tuple(universe.to_parameters() for universe in universes),
            "baseline": baseline,
            "objective": objective,
            "sample_count_metric": sample_count_metric,
            "evaluator_name": evaluator_name,
            "evaluator_version": evaluator_version,
            "code_id": code_id,
        },
        namespace="universe-perturbation-input",
    )
    return AnalysisResult(
        metadata=ResultMetadata(
            method="robustness.universe_perturbation",
            method_version=1,
            parameters={
                "baseline": baseline,
                "objective": objective,
                "direction": direction,
                "sample_count_metric": sample_count_metric,
                "evaluator_name": evaluator_name,
                "evaluator_version": evaluator_version,
                "code_id": code_id,
                "failure_policy": failure_policy,
            },
            input_fingerprint=input_fingerprint,
        ),
        metrics={
            "universe_count": len(universes),
            "successful_universes": len(objectives),
            "failed_universes": failed,
            "retrospective_universes": len(retrospective),
            "minimum_composition_jaccard": min_jaccard,
            "maximum_composition_change": 1.0 - min_jaccard,
            "worst_objective": worst,
            "best_objective": best,
            "objective_dispersion": (
                float(np.std(objectives, ddof=1)) if len(objectives) > 1 else None
            ),
        },
        findings=tuple(findings),
        tables={"universes": tuple(rows)},
        warnings=(
            "Point-in-time declarations are provenance claims and do not independently prove "
            "source safety.",
        ),
    )


__all__ = [
    "Distribution",
    "FailurePolicy",
    "ObjectiveDirection",
    "PerturbationSpec",
    "Subperiod",
    "UniverseScenario",
    "continuous_perturbation",
    "subperiod_analysis",
    "universe_perturbation",
]
