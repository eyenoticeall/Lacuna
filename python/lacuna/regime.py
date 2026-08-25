"""Point-in-time-aware regime classification and conditional evidence."""

from __future__ import annotations

import math
from numbers import Real
from typing import Literal, TypeAlias

import numpy as np
import numpy.typing as npt
import polars as pl

from lacuna._frames import (
    eager_frame,
    frame_records,
    require_identifier,
    require_no_nulls,
    require_numeric,
    require_time_key,
    require_unique,
)
from lacuna.exceptions import DataContractError, MethodContractError
from lacuna.experiment import fingerprint
from lacuna.types import AnalysisResult, Finding, FindingState, JsonValue, ResultMetadata, Severity

QuantileMethod: TypeAlias = Literal["fixed", "expanding", "rolling", "retrospective"]
ClassificationMode: TypeAlias = Literal["point_in_time", "retrospective"]
FloatArray: TypeAlias = npt.NDArray[np.float64]


def _validate_probability(value: float, *, name: str) -> None:
    if not math.isfinite(value) or not 0.0 < value < 1.0:
        raise MethodContractError(f"{name} must be finite and in (0, 1)")


def _validate_label(value: str, *, name: str) -> str:
    if not value or value.strip() != value:
        raise MethodContractError(f"{name} must be a non-empty trimmed string")
    return value


def _availability_violations(
    frame: pl.DataFrame,
    *,
    time: str,
    available_time: str | None,
    name: str,
) -> int:
    if available_time is None:
        return 0
    require_no_nulls(frame, [available_time], name=name)
    if frame.schema[available_time] != frame.schema[time]:
        raise DataContractError(
            f"{name} available-time column must match {time}={frame.schema[time]}; "
            f"got {available_time}={frame.schema[available_time]}"
        )
    return int(frame.select((pl.col(available_time) > pl.col(time)).sum()).item())


def _portable_records(frame: pl.DataFrame) -> tuple[JsonValue, ...]:
    """Serialize temporal columns without requiring the host's IANA timezone database."""

    expressions: list[pl.Expr] = []
    for column, dtype in frame.schema.items():
        if isinstance(dtype, pl.Datetime) and dtype.time_zone is not None:
            expressions.append(
                pl.col(column)
                .dt.convert_time_zone("UTC")
                .dt.strftime("%+")
                .str.replace(r"\+00:00$", "Z")
                .alias(column)
            )
        elif dtype == pl.Date or isinstance(dtype, pl.Datetime):
            expressions.append(pl.col(column).cast(pl.String).alias(column))
    normalized = frame.with_columns(expressions) if expressions else frame
    return frame_records(normalized)


def quantile_regimes(
    data: object,
    *,
    time: str = "time",
    value: str = "value",
    method: QuantileMethod = "expanding",
    lower_quantile: float = 0.25,
    upper_quantile: float = 0.75,
    min_history: int = 20,
    window: int | None = None,
    lower_threshold: float | None = None,
    upper_threshold: float | None = None,
    low_label: str = "low",
    middle_label: str = "middle",
    high_label: str = "high",
    unknown_label: str = "unknown",
    available_time: str | None = None,
) -> AnalysisResult:
    """Classify a scalar with fixed, trailing expanding/rolling, or retrospective quantiles."""

    if method not in {"fixed", "expanding", "rolling", "retrospective"}:
        raise MethodContractError("method must be fixed, expanding, rolling, or retrospective")
    _validate_probability(lower_quantile, name="lower_quantile")
    _validate_probability(upper_quantile, name="upper_quantile")
    if lower_quantile >= upper_quantile:
        raise MethodContractError("lower_quantile must be below upper_quantile")
    if min_history < 1:
        raise MethodContractError("min_history must be positive")
    labels = [
        _validate_label(low_label, name="low_label"),
        _validate_label(middle_label, name="middle_label"),
        _validate_label(high_label, name="high_label"),
        _validate_label(unknown_label, name="unknown_label"),
    ]
    if len(labels) != len(set(labels)):
        raise MethodContractError("regime labels must be unique")
    if method == "rolling":
        if window is None or window < min_history:
            raise MethodContractError("rolling window must be at least min_history")
    elif window is not None:
        raise MethodContractError("window is only valid for rolling quantiles")
    if method == "fixed":
        if lower_threshold is None or upper_threshold is None:
            raise MethodContractError("fixed quantiles require lower_threshold and upper_threshold")
        if (
            not math.isfinite(lower_threshold)
            or not math.isfinite(upper_threshold)
            or lower_threshold >= upper_threshold
        ):
            raise MethodContractError("fixed thresholds must be finite and strictly ordered")
    elif lower_threshold is not None or upper_threshold is not None:
        raise MethodContractError("explicit thresholds are only valid for method='fixed'")

    required = [time, value]
    if available_time is not None:
        required.append(available_time)
    frame, diagnostics = eager_frame(data, required=required)
    if frame.is_empty():
        raise DataContractError("regime source must contain at least one row")
    require_no_nulls(frame, [time], name="regime source")
    require_time_key(frame, time, name="regime source")
    require_numeric(frame, [value])
    require_unique(frame, [time], name="regime source")
    future_availability = _availability_violations(
        frame,
        time=time,
        available_time=available_time,
        name="regime source",
    )
    diagnostics = diagnostics.with_execution(
        "sort_time",
        f"{method}_quantile_thresholds",
        "classify_regime",
    )
    selected_columns = [time, value]
    if available_time is not None:
        selected_columns.append(available_time)
    ordered = frame.select(selected_columns).sort(time)
    values = ordered.get_column(value).cast(pl.Float64).to_numpy()
    if bool(np.isinf(values).any()):
        raise DataContractError("regime value contains infinity")

    lower_values: list[float | None] = []
    upper_values: list[float | None] = []
    history_counts: list[int] = []
    regimes: list[str] = []
    retrospective_history = values[np.isfinite(values)]
    retrospective_lower = (
        float(np.quantile(retrospective_history, lower_quantile))
        if retrospective_history.size
        else None
    )
    retrospective_upper = (
        float(np.quantile(retrospective_history, upper_quantile))
        if retrospective_history.size
        else None
    )
    for position, observed in enumerate(values):
        if method == "fixed":
            history_count = 0
            lower = lower_threshold
            upper = upper_threshold
        elif method == "retrospective":
            history_count = int(retrospective_history.size)
            lower = retrospective_lower
            upper = retrospective_upper
        else:
            start = 0 if method == "expanding" else max(0, position - int(window or 0))
            history = values[start:position]
            finite_history = history[np.isfinite(history)]
            history_count = int(finite_history.size)
            if history_count >= min_history:
                lower = float(np.quantile(finite_history, lower_quantile))
                upper = float(np.quantile(finite_history, upper_quantile))
            else:
                lower = None
                upper = None
        lower_values.append(lower)
        upper_values.append(upper)
        history_counts.append(history_count)
        if not math.isfinite(float(observed)) or lower is None or upper is None:
            regimes.append(unknown_label)
        elif observed <= lower:
            regimes.append(low_label)
        elif observed >= upper:
            regimes.append(high_label)
        else:
            regimes.append(middle_label)

    output = ordered.with_columns(
        pl.Series("threshold_lower", lower_values, dtype=pl.Float64),
        pl.Series("threshold_upper", upper_values, dtype=pl.Float64),
        pl.Series("history_count", history_counts, dtype=pl.Int64),
        pl.Series("regime", regimes, dtype=pl.String),
    )
    unknown_count = regimes.count(unknown_label)
    findings: list[Finding] = []
    if method == "retrospective":
        findings.append(
            Finding(
                code="REGIME_RETROSPECTIVE_THRESHOLDS",
                title="Regime thresholds use the full sample",
                message="Earlier labels depend on later observations and are descriptive only.",
                state=FindingState.WARN,
                severity=Severity.HIGH,
                category="bias",
            )
        )
    elif future_availability:
        findings.append(
            Finding(
                code="REGIME_SOURCE_NOT_AVAILABLE",
                title="Regime source was unavailable at observation time",
                message="One or more point-in-time labels use a source published later.",
                state=FindingState.FAIL,
                severity=Severity.HIGH,
                category="bias",
                evidence={"future_available_rows": future_availability},
            )
        )
    else:
        findings.append(
            Finding(
                code="REGIME_THRESHOLDS_POINT_IN_TIME",
                title="Regime thresholds exclude future observations",
                message="Fixed or trailing thresholds do not use later source values.",
                state=FindingState.PASS,
                severity=Severity.INFO,
                category="bias",
            )
        )
    if unknown_count:
        findings.append(
            Finding(
                code="REGIME_UNCLASSIFIED_ROWS",
                title="Some regime rows are unclassified",
                message="Insufficient history or missing values remain visible as unknown.",
                state=FindingState.UNKNOWN,
                severity=Severity.LOW,
                category="robustness",
                evidence={"unknown_rows": unknown_count, "row_count": output.height},
            )
        )
    records = _portable_records(output)
    input_fingerprint = fingerprint(
        {
            "rows": records,
            "method": method,
            "lower_quantile": lower_quantile,
            "upper_quantile": upper_quantile,
            "min_history": min_history,
            "window": window,
            "lower_threshold": lower_threshold,
            "upper_threshold": upper_threshold,
        },
        namespace="quantile-regimes-input",
    )
    return AnalysisResult(
        metadata=ResultMetadata(
            method="regime.quantile_regimes",
            method_version=1,
            parameters={
                "time": time,
                "value": value,
                "method": method,
                "lower_quantile": lower_quantile,
                "upper_quantile": upper_quantile,
                "min_history": min_history,
                "window": window,
                "lower_threshold": lower_threshold,
                "upper_threshold": upper_threshold,
                "labels": {
                    "low": low_label,
                    "middle": middle_label,
                    "high": high_label,
                    "unknown": unknown_label,
                },
                "available_time": available_time,
                "input": diagnostics.to_parameters(),
            },
            input_fingerprint=input_fingerprint,
        ),
        metrics={
            "row_count": output.height,
            "classified_rows": output.height - unknown_count,
            "unknown_rows": unknown_count,
            "future_available_rows": future_availability,
        },
        findings=tuple(findings),
        tables={"regimes": records},
        warnings=(
            "Quantile labels describe the supplied scalar and do not establish a causal "
            "macro state.",
        ),
    )


def _effective_sample_size(values: FloatArray) -> float:
    size = int(values.size)
    if size < 3 or float(np.std(values, ddof=1)) == 0.0:
        return float(size)
    correlation = float(np.corrcoef(values[:-1], values[1:])[0, 1])
    if not math.isfinite(correlation) or correlation <= 0.0:
        return float(size)
    return max(1.0, min(float(size), size / (1.0 + 2.0 * correlation)))


def _maximum_drawdown(outcomes: FloatArray) -> float:
    if outcomes.size == 0:
        return 0.0
    cumulative: FloatArray = np.cumsum(outcomes)
    wealth: FloatArray = np.concatenate((np.asarray([0.0]), cumulative))
    running_peak: FloatArray = np.maximum.accumulate(wealth)
    return float(np.min(wealth - running_peak))


def _row_float(row: dict[str, JsonValue], key: str) -> float:
    value = row[key]
    if not isinstance(value, Real) or isinstance(value, bool):  # pragma: no cover - invariant
        raise RuntimeError(f"internal regime row {key!r} is not numeric")
    return float(value)


def regime_analysis(
    data: object,
    *,
    time: str = "time",
    regime: str = "regime",
    outcome: str = "outcome",
    classification_mode: ClassificationMode,
    available_time: str | None = None,
    mutually_exclusive: bool = True,
    unknown_label: str = "unknown",
    min_observations: int = 20,
    annualization: float = 1.0,
    concentration_threshold: float = 0.6,
) -> AnalysisResult:
    """Summarize conditional outcomes and quantify regime dependence and concentration."""

    if classification_mode not in {"point_in_time", "retrospective"}:
        raise MethodContractError("classification_mode must be 'point_in_time' or 'retrospective'")
    _validate_label(unknown_label, name="unknown_label")
    if min_observations < 1:
        raise MethodContractError("min_observations must be positive")
    if not math.isfinite(annualization) or annualization <= 0.0:
        raise MethodContractError("annualization must be positive and finite")
    if not math.isfinite(concentration_threshold) or not 0.0 < concentration_threshold <= 1.0:
        raise MethodContractError("concentration_threshold must be in (0, 1]")

    required = [time, regime, outcome]
    if available_time is not None:
        required.append(available_time)
    frame, diagnostics = eager_frame(data, required=required)
    if frame.is_empty():
        raise DataContractError("regime evidence must contain at least one row")
    require_no_nulls(frame, [time], name="regime evidence")
    require_time_key(frame, time, name="regime evidence")
    require_identifier(frame, regime, name="regime evidence")
    require_numeric(frame, [outcome])
    if mutually_exclusive:
        require_unique(frame, [time], name="mutually exclusive regime evidence")
    else:
        require_unique(frame, [time, regime], name="overlapping regime evidence")
    future_availability = _availability_violations(
        frame,
        time=time,
        available_time=available_time,
        name="regime evidence",
    )
    diagnostics = diagnostics.with_execution(
        "sort_time",
        "group_by_regime",
        "conditional_outcome_statistics",
        "regime_concentration",
    )
    selected_columns = [time, regime, outcome]
    if available_time is not None:
        selected_columns.append(available_time)
    ordered = (
        frame.select(selected_columns)
        .with_columns(
            pl.col(regime).cast(pl.String).fill_null(unknown_label),
            pl.col(outcome).cast(pl.Float64),
        )
        .sort([time, regime])
    )
    infinite_count = int(ordered.select(pl.col(outcome).is_infinite().sum()).item())
    if infinite_count:
        raise DataContractError(f"regime outcome contains {infinite_count} infinite values")
    valid_all = ordered.filter(pl.col(outcome).is_not_null() & ~pl.col(outcome).is_nan())
    all_outcomes = valid_all.get_column(outcome).to_numpy()
    net_total = float(np.sum(all_outcomes))
    absolute_total = float(np.sum(np.abs(all_outcomes)))

    rows: list[dict[str, JsonValue]] = []
    findings: list[Finding] = []
    labels = sorted(ordered.get_column(regime).unique().to_list())
    for label in labels:
        subset = ordered.filter(pl.col(regime) == label)
        valid = subset.filter(pl.col(outcome).is_not_null() & ~pl.col(outcome).is_nan())
        values = valid.get_column(outcome).to_numpy()
        raw_count = subset.height
        sample_count = int(values.size)
        excluded = raw_count - sample_count
        effective_count = _effective_sample_size(values)
        mean = float(np.mean(values)) if sample_count else None
        standard_deviation = float(np.std(values, ddof=1)) if sample_count > 1 else None
        sharpe = (
            mean / standard_deviation * math.sqrt(annualization)
            if mean is not None and standard_deviation is not None and standard_deviation > 0.0
            else None
        )
        confidence_half_width = (
            1.96 * standard_deviation / math.sqrt(effective_count)
            if standard_deviation is not None and effective_count > 0.0
            else None
        )
        total = float(np.sum(values)) if sample_count else 0.0
        absolute_contribution = float(np.sum(np.abs(values))) if sample_count else 0.0
        observation_share = raw_count / ordered.height
        absolute_share = absolute_contribution / absolute_total if absolute_total > 0.0 else None
        net_share = total / net_total if net_total != 0.0 else None
        rows.append(
            {
                "regime": str(label),
                "raw_observations": raw_count,
                "sample_count": sample_count,
                "excluded_outcomes": excluded,
                "effective_sample_size": effective_count,
                "mean_outcome": mean,
                "standard_deviation": standard_deviation,
                "sharpe": sharpe,
                "hit_rate": (float(np.mean(values > 0.0)) if sample_count else None),
                "confidence_lower": (
                    mean - confidence_half_width
                    if mean is not None and confidence_half_width is not None
                    else None
                ),
                "confidence_upper": (
                    mean + confidence_half_width
                    if mean is not None and confidence_half_width is not None
                    else None
                ),
                "total_outcome": total,
                "maximum_drawdown": _maximum_drawdown(values),
                "observation_share": observation_share,
                "net_outcome_share": net_share,
                "absolute_outcome_share": absolute_share,
                "leave_one_regime_out_total": net_total - total,
            }
        )
        if sample_count < min_observations:
            findings.append(
                Finding(
                    code="REGIME_INSUFFICIENT_EVIDENCE",
                    title=f"Regime {label!s} has insufficient evidence",
                    message=(
                        "The regime remains visible but has fewer valid outcomes than required."
                    ),
                    state=FindingState.UNKNOWN,
                    severity=Severity.MEDIUM,
                    category="robustness",
                    evidence={
                        "regime": str(label),
                        "sample_count": sample_count,
                        "minimum": min_observations,
                    },
                )
            )

    unknown_rows = int(ordered.filter(pl.col(regime) == unknown_label).height)
    if unknown_rows:
        findings.append(
            Finding(
                code="REGIME_UNKNOWN_CLASSIFICATION",
                title="Regime evidence contains unknown classifications",
                message="Unclassified observations remain visible as a separate conditional group.",
                state=FindingState.UNKNOWN,
                severity=Severity.MEDIUM,
                category="robustness",
                evidence={"unknown_rows": unknown_rows},
            )
        )
    if classification_mode == "retrospective":
        findings.append(
            Finding(
                code="REGIME_ANALYSIS_RETROSPECTIVE",
                title="Regime analysis is retrospective",
                message="Conditional results are descriptive and are not point-in-time evidence.",
                state=FindingState.WARN,
                severity=Severity.HIGH,
                category="bias",
            )
        )
    elif available_time is None:
        findings.append(
            Finding(
                code="REGIME_AVAILABILITY_UNKNOWN",
                title="Regime source availability is unknown",
                message=(
                    "Point-in-time safety cannot be established without availability timestamps."
                ),
                state=FindingState.UNKNOWN,
                severity=Severity.MEDIUM,
                category="bias",
            )
        )
    elif future_availability:
        findings.append(
            Finding(
                code="REGIME_AVAILABILITY_LEAKAGE",
                title="Regime classifications use unavailable source data",
                message="At least one source value became available after its observation time.",
                state=FindingState.FAIL,
                severity=Severity.HIGH,
                category="bias",
                evidence={"future_available_rows": future_availability},
            )
        )
    else:
        findings.append(
            Finding(
                code="REGIME_AVAILABILITY_POINT_IN_TIME",
                title="Regime sources are available by observation time",
                message="No supplied availability timestamp is later than its observation.",
                state=FindingState.PASS,
                severity=Severity.INFO,
                category="bias",
            )
        )
    if not mutually_exclusive:
        findings.append(
            Finding(
                code="REGIME_LABELS_OVERLAP",
                title="Regime labels overlap",
                message="Observation and outcome shares count label rows, not unique timestamps.",
                state=FindingState.WARN,
                severity=Severity.MEDIUM,
                category="robustness",
            )
        )

    shares = [
        _row_float(row, "absolute_outcome_share")
        for row in rows
        if row["absolute_outcome_share"] is not None
    ]
    concentration_hhi = sum(share**2 for share in shares) if shares else None
    top_row = (
        max(
            (row for row in rows if row["absolute_outcome_share"] is not None),
            key=lambda row: _row_float(row, "absolute_outcome_share"),
            default=None,
        )
        if rows
        else None
    )
    top_absolute_share = (
        _row_float(top_row, "absolute_outcome_share") if top_row is not None else None
    )
    top_observation_share = (
        _row_float(top_row, "observation_share") if top_row is not None else None
    )
    if top_absolute_share is not None and top_absolute_share >= concentration_threshold:
        if top_row is None:  # pragma: no cover - derived from top_absolute_share
            raise RuntimeError("regime concentration row is unavailable")
        findings.append(
            Finding(
                code="REGIME_OUTCOME_CONCENTRATION",
                title="Outcome is concentrated in one regime",
                message="One regime supplies a large share of absolute outcome contribution.",
                state=FindingState.WARN,
                severity=Severity.HIGH,
                category="robustness",
                evidence={
                    "regime": str(top_row["regime"]),
                    "absolute_outcome_share": top_absolute_share,
                    "observation_share": top_observation_share,
                    "threshold": concentration_threshold,
                },
            )
        )

    records = _portable_records(ordered)
    input_fingerprint = fingerprint(
        {
            "rows": records,
            "classification_mode": classification_mode,
            "mutually_exclusive": mutually_exclusive,
            "unknown_label": unknown_label,
            "min_observations": min_observations,
            "annualization": annualization,
        },
        namespace="regime-analysis-input",
    )
    return AnalysisResult(
        metadata=ResultMetadata(
            method="regime.analysis",
            method_version=1,
            parameters={
                "time": time,
                "regime": regime,
                "outcome": outcome,
                "classification_mode": classification_mode,
                "available_time": available_time,
                "mutually_exclusive": mutually_exclusive,
                "unknown_label": unknown_label,
                "min_observations": min_observations,
                "annualization": annualization,
                "effective_sample_size": "lag1_positive_autocorrelation",
                "confidence_interval": "normal_95_percent_effective_n",
                "concentration_basis": "absolute_outcome_over_label_rows",
                "input": diagnostics.to_parameters(),
            },
            input_fingerprint=input_fingerprint,
        ),
        metrics={
            "row_count": ordered.height,
            "valid_outcomes": valid_all.height,
            "excluded_outcomes": ordered.height - valid_all.height,
            "regime_count": len(rows),
            "unknown_rows": unknown_rows,
            "future_available_rows": future_availability,
            "total_outcome": net_total,
            "total_absolute_outcome": absolute_total,
            "top_regime": str(top_row["regime"]) if top_row is not None else None,
            "top_absolute_outcome_share": top_absolute_share,
            "top_observation_share": top_observation_share,
            "absolute_outcome_hhi": concentration_hhi,
        },
        findings=tuple(findings),
        tables={"conditional_evidence": tuple(rows), "observations": records},
        warnings=(
            "Net outcome shares may be negative or exceed one when regimes contain losses.",
            "Overlapping regimes double-count observations and outcomes across labels.",
        )
        if not mutually_exclusive
        else ("Net outcome shares may be negative or exceed one when regimes contain losses.",),
    )


__all__ = [
    "ClassificationMode",
    "QuantileMethod",
    "quantile_regimes",
    "regime_analysis",
]
