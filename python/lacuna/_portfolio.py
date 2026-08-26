"""Explicit one-horizon diagnostic portfolio projections."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, TypeAlias

import numpy as np
import numpy.typing as npt
import polars as pl

from lacuna._attrition import attrition_record
from lacuna._frames import (
    eager_frame,
    frame_records,
    paired_numeric_policy,
    require_compatible_keys,
    require_no_nulls,
    require_unique,
    validate_label_intervals,
    validate_panel_schema,
)
from lacuna._signal_transform import SignalTransformResult
from lacuna.exceptions import DataContractError, MethodContractError
from lacuna.labels import LabelResult
from lacuna.types import AnalysisResult, Finding, FindingState, JsonValue, ResultMetadata, Severity

FloatArray: TypeAlias = npt.NDArray[np.float64]
Weighting = Literal["equal", "rank", "absolute_signal"]
IncompleteGroupPolicy = Literal["raise", "drop"]


@dataclass(frozen=True, slots=True)
class PortfolioProjectionResult:
    """Immutable projected cohort rows plus structured diagnostic evidence."""

    _frame: pl.DataFrame
    evidence: AnalysisResult

    @property
    def frame(self) -> pl.DataFrame:
        """Return a shallow clone of result-owned projection rows."""

        return self._frame.clone()

    @property
    def metadata(self) -> ResultMetadata:
        """Expose projection provenance."""

        return self.evidence.metadata

    def to_json(self, *, indent: int | None = 2) -> str:
        """Serialize compact evidence without embedding the projection frame."""

        return self.evidence.to_json(indent=indent)


def _bucket_selection(values: Sequence[int], *, name: str) -> tuple[int, ...]:
    normalized = tuple(values)
    if not normalized or any(
        isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in normalized
    ):
        raise MethodContractError(f"{name} must contain positive integer bucket identifiers")
    if len(set(normalized)) != len(normalized):
        raise MethodContractError(f"{name} must not contain duplicate buckets")
    return tuple(sorted(normalized))


def _leg_scores(frame: pl.DataFrame, *, leg: str, weighting: Weighting) -> FloatArray:
    values: FloatArray = frame.get_column("signal").to_numpy().astype(np.float64, copy=False)
    if weighting == "equal":
        return np.ones(frame.height, dtype=np.float64)
    if weighting == "absolute_signal":
        scores = np.abs(values)
        return scores if float(scores.sum()) > 0.0 else np.ones(frame.height, dtype=np.float64)
    strength = values if leg == "long" else -values
    return (
        pl.Series("strength", strength)
        .rank(method="average")
        .to_numpy()
        .astype(np.float64, copy=False)
    )


def _group_identity(frame: pl.DataFrame, columns: Sequence[str]) -> tuple[object, ...]:
    return tuple(frame.get_column(column)[0] for column in columns)


def _mean_float(series: pl.Series) -> float | None:
    value = series.mean()
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def portfolio_projection(
    bucketed: SignalTransformResult,
    labels: object,
    *,
    horizon: str,
    long_buckets: Sequence[int],
    short_buckets: Sequence[int],
    weighting: Weighting = "equal",
    gross_exposure: float = 1.0,
    net_exposure: float = 0.0,
    group_neutral: str | Sequence[str] | None = None,
    incomplete_group_policy: IncompleteGroupPolicy = "raise",
) -> PortfolioProjectionResult:
    """Construct explicit target weights and arithmetic forward-return contributions."""

    if (
        not isinstance(bucketed, SignalTransformResult)
        or bucketed.metadata.method != "signal.bucketize"
    ):
        raise MethodContractError("bucketed must be a SignalTransformResult from signal.bucketize")
    if not isinstance(horizon, str) or not horizon:
        raise MethodContractError("horizon must be one explicit non-empty label horizon")
    long_selection = _bucket_selection(long_buckets, name="long_buckets")
    short_selection = _bucket_selection(short_buckets, name="short_buckets")
    if set(long_selection).intersection(short_selection):
        raise MethodContractError("long_buckets and short_buckets must be disjoint")
    if weighting not in {"equal", "rank", "absolute_signal"}:
        raise MethodContractError("weighting must be equal, rank, or absolute_signal")
    if (
        isinstance(gross_exposure, bool)
        or not isinstance(gross_exposure, int | float)
        or not math.isfinite(float(gross_exposure))
        or gross_exposure <= 0.0
    ):
        raise MethodContractError("gross_exposure must be finite and positive")
    if (
        isinstance(net_exposure, bool)
        or not isinstance(net_exposure, int | float)
        or not math.isfinite(float(net_exposure))
        or abs(net_exposure) > gross_exposure
    ):
        raise MethodContractError("net_exposure must be finite and satisfy abs(net) <= gross")
    if incomplete_group_policy not in {"raise", "drop"}:
        raise MethodContractError("incomplete_group_policy must be 'raise' or 'drop'")
    if group_neutral is None:
        group_columns: tuple[str, ...] = ()
    elif isinstance(group_neutral, str):
        group_columns = (group_neutral,)
    else:
        group_columns = tuple(group_neutral)
    if any(not column for column in group_columns) or len(set(group_columns)) != len(group_columns):
        raise MethodContractError("group_neutral columns must be non-empty and unique")

    bucket_frame = bucketed.frame
    required_bucket = ["observation_time", "instrument", "signal", "bucket", *group_columns]
    missing_bucket = [column for column in required_bucket if column not in bucket_frame.columns]
    if missing_bucket:
        raise DataContractError(
            "bucketed signal is missing required columns: " + ", ".join(missing_bucket)
        )
    validate_panel_schema(
        bucket_frame,
        time="observation_time",
        instrument="instrument",
        numeric=["signal", "bucket"],
        name="bucketed signal",
    )
    require_no_nulls(bucket_frame, group_columns, name="portfolio group columns")
    if not bucket_frame.schema["bucket"].is_integer():
        raise DataContractError("bucket assignments must use an integer dtype")
    requested = set(long_selection).union(short_selection)
    available = set(bucket_frame.get_column("bucket").unique().to_list())
    absent = sorted(requested.difference(available))
    if absent:
        raise DataContractError(f"requested portfolio buckets are absent: {absent}")

    label_source = labels.frame if isinstance(labels, LabelResult) else labels
    label_frame, label_diagnostics = eager_frame(
        label_source,
        required=(
            "observation_time",
            "instrument",
            "horizon",
            "entry_time",
            "label_end",
            "forward_return",
        ),
    )
    validate_panel_schema(
        label_frame,
        time="observation_time",
        instrument="instrument",
        numeric=["forward_return"],
        name="labels",
        unique=False,
    )
    validate_label_intervals(label_frame, observation_time="observation_time")
    require_no_nulls(label_frame, ["horizon", "entry_time", "label_end"], name="labels")
    selected_labels = label_frame.filter(pl.col("horizon") == horizon)
    if selected_labels.is_empty():
        raise DataContractError(f"labels contain no rows for horizon {horizon!r}")
    require_unique(selected_labels, ["observation_time", "instrument"], name="selected labels")
    require_compatible_keys(
        bucket_frame,
        selected_labels,
        pairs=(("observation_time", "observation_time"), ("instrument", "instrument")),
    )
    label_projection = selected_labels.select(
        "observation_time",
        "instrument",
        "horizon",
        "entry_time",
        "label_end",
        "forward_return",
        pl.lit(True).alias("_label_match"),
    )
    selected_bucket_rows = bucket_frame.filter(pl.col("bucket").is_in(list(requested))).select(
        *required_bucket
    )
    joined = selected_bucket_rows.join(
        label_projection,
        on=["observation_time", "instrument"],
        how="left",
        validate="1:1",
    )
    matched = joined.filter(pl.col("_label_match").fill_null(False)).drop("_label_match")
    matched, numeric_excluded = paired_numeric_policy(
        matched,
        ["signal", "forward_return"],
        null_policy="drop",
    )
    if matched.is_empty():
        raise DataContractError("no finite bucket/label rows align for the requested horizon")

    long_allocation = (float(gross_exposure) + float(net_exposure)) / 2.0
    short_allocation = (float(gross_exposure) - float(net_exposure)) / 2.0
    weighted_frames: list[pl.DataFrame] = []
    incomplete_rows = 0
    fallback_groups = 0
    for cohort in matched.sort(["observation_time", *group_columns, "instrument"]).partition_by(
        "observation_time", maintain_order=True
    ):
        subgroups = (
            cohort.partition_by(list(group_columns), maintain_order=True)
            if group_columns
            else [cohort]
        )
        long_groups = {
            _group_identity(group, group_columns)
            for group in subgroups
            if group.filter(pl.col("bucket").is_in(list(long_selection))).height
        }
        short_groups = {
            _group_identity(group, group_columns)
            for group in subgroups
            if group.filter(pl.col("bucket").is_in(list(short_selection))).height
        }
        eligible_groups = long_groups.intersection(short_groups)
        incomplete_groups = long_groups.symmetric_difference(short_groups)
        if incomplete_groups and incomplete_group_policy == "raise":
            raise DataContractError(
                "portfolio cohort contains a one-sided group; use incomplete_group_policy='drop' "
                "to exclude and renormalize it"
            )
        if not eligible_groups:
            raise DataContractError("portfolio cohort has no groups containing both legs")
        group_allocation_count = len(eligible_groups)
        for group in subgroups:
            identity = _group_identity(group, group_columns)
            if identity not in eligible_groups:
                incomplete_rows += group.height
                continue
            for leg, selection, allocation, sign in (
                ("long", long_selection, long_allocation, 1.0),
                ("short", short_selection, short_allocation, -1.0),
            ):
                leg_frame = group.filter(pl.col("bucket").is_in(list(selection))).sort("instrument")
                scores = _leg_scores(leg_frame, leg=leg, weighting=weighting)
                score_sum = float(scores.sum())
                if weighting == "absolute_signal" and np.all(
                    leg_frame.get_column("signal").to_numpy() == 0.0
                ):
                    fallback_groups += 1
                magnitudes = scores / score_sum * (allocation / group_allocation_count)
                target_weights = sign * magnitudes
                weighted_frames.append(
                    leg_frame.with_columns(
                        pl.lit(leg).alias("leg"),
                        pl.Series("target_weight", target_weights, dtype=pl.Float64),
                    ).with_columns(
                        (pl.col("target_weight") * pl.col("forward_return")).alias("contribution")
                    )
                )
    if not weighted_frames:
        raise DataContractError("no portfolio rows remain after group policy")
    output = (
        pl.concat(weighted_frames, how="vertical")
        .select(
            "observation_time",
            "entry_time",
            "label_end",
            "instrument",
            "horizon",
            "bucket",
            "leg",
            "target_weight",
            "forward_return",
            "contribution",
            "signal",
            *group_columns,
        )
        .sort(["observation_time", "leg", *group_columns, "bucket", "instrument"])
    )

    exposure = output.group_by("observation_time", maintain_order=True).agg(
        pl.col("target_weight").filter(pl.col("leg") == "long").sum().alias("long_exposure"),
        pl.col("target_weight").filter(pl.col("leg") == "short").sum().alias("short_exposure"),
        pl.col("target_weight").abs().sum().alias("gross_exposure"),
        pl.col("target_weight").sum().alias("net_exposure"),
        pl.len().alias("n_positions"),
    )
    tolerance = 1e-10
    for row in exposure.iter_rows(named=True):
        long_value = float(row["long_exposure"])
        short_value = float(row["short_exposure"])
        gross_value = float(row["gross_exposure"])
        net_value = float(row["net_exposure"])
        if not (
            math.isclose(long_value, long_allocation, abs_tol=tolerance, rel_tol=tolerance)
            and math.isclose(short_value, -short_allocation, abs_tol=tolerance, rel_tol=tolerance)
            and math.isclose(
                gross_value, float(gross_exposure), abs_tol=tolerance, rel_tol=tolerance
            )
            and math.isclose(net_value, float(net_exposure), abs_tol=tolerance, rel_tol=tolerance)
        ):
            raise DataContractError(
                "portfolio target weights failed gross/net exposure reconciliation"
            )
    cohort_returns = output.group_by(
        ["observation_time", "entry_time", "label_end", "horizon"], maintain_order=True
    ).agg(
        pl.col("contribution").sum().alias("portfolio_return"),
        pl.col("contribution").filter(pl.col("leg") == "long").sum().alias("long_contribution"),
        pl.col("contribution").filter(pl.col("leg") == "short").sum().alias("short_contribution"),
        pl.len().alias("n_positions"),
    )
    concentration = output.group_by("observation_time", maintain_order=True).agg(
        (pl.col("target_weight").abs() / pl.col("target_weight").abs().sum())
        .pow(2)
        .sum()
        .alias("weight_hhi"),
        pl.col("target_weight").abs().max().alias("max_absolute_weight"),
    )
    period_frames = output.partition_by("observation_time", maintain_order=True)
    turnover_rows: list[dict[str, object]] = []
    previous: dict[object, float] | None = None
    previous_time: object | None = None
    for period_frame in period_frames:
        observation_time = period_frame.get_column("observation_time")[0]
        current = {
            row["instrument"]: float(row["target_weight"])
            for row in period_frame.select("instrument", "target_weight").to_dicts()
        }
        if previous is not None:
            instruments = set(previous).union(current)
            one_way = 0.5 * sum(
                abs(current.get(item, 0.0) - previous.get(item, 0.0)) for item in instruments
            )
            turnover_rows.append(
                {
                    "previous_observation_time": previous_time,
                    "observation_time": observation_time,
                    "one_way_target_turnover": one_way,
                    "n_instruments": len(instruments),
                }
            )
        previous = current
        previous_time = observation_time
    turnover = pl.DataFrame(turnover_rows) if turnover_rows else pl.DataFrame()
    alignment_excluded = selected_bucket_rows.height - matched.height
    findings: list[Finding] = []
    if incomplete_rows:
        findings.append(
            Finding(
                code="PORTFOLIO_INCOMPLETE_GROUPS_EXCLUDED",
                title="One-sided portfolio groups were excluded",
                message="Explicit drop policy removed groups lacking one requested leg.",
                state=FindingState.WARN,
                severity=Severity.MEDIUM,
                category="statistical_validity",
                evidence={"excluded_rows": incomplete_rows},
            )
        )
    if fallback_groups:
        findings.append(
            Finding(
                code="PORTFOLIO_ZERO_SIGNAL_FALLBACK",
                title="Zero absolute-signal groups used equal weights",
                message="Absolute-signal weights were undefined and fell back to equal shares.",
                state=FindingState.WARN,
                severity=Severity.LOW,
                category="statistical_validity",
                evidence={"groups": fallback_groups},
            )
        )
    attrition: tuple[JsonValue, ...] = (
        attrition_record(
            "label_alignment",
            "missing_or_non_finite_requested_horizon_label",
            input_rows=selected_bucket_rows.height,
            retained_rows=matched.height,
            policy="drop_with_evidence",
        ),
        attrition_record(
            "group_neutrality",
            "one_sided_joint_group",
            input_rows=matched.height,
            retained_rows=output.height,
            policy=incomplete_group_policy,
        ),
    )
    evidence = AnalysisResult(
        metadata=ResultMetadata(
            method="signal.portfolio_projection",
            method_version=1,
            parameters={
                "source_method": bucketed.metadata.method,
                "horizon": horizon,
                "long_buckets": long_selection,
                "short_buckets": short_selection,
                "weighting": weighting,
                "gross_exposure": float(gross_exposure),
                "net_exposure": float(net_exposure),
                "long_allocation": long_allocation,
                "short_allocation": short_allocation,
                "group_neutral": group_columns,
                "incomplete_group_policy": incomplete_group_policy,
                "compounding": False,
                "overlapping_holdings_resolution": False,
                "execution_simulation": False,
                "label_input": label_diagnostics.to_parameters(),
            },
        ),
        metrics={
            "n_rows": output.height,
            "n_cohorts": output.get_column("observation_time").n_unique(),
            "matched_rows": matched.height,
            "excluded_alignment_rows": alignment_excluded,
            "excluded_non_finite_rows": numeric_excluded,
            "excluded_incomplete_group_rows": incomplete_rows,
            "mean_cohort_return": _mean_float(cohort_returns.get_column("portfolio_return")),
            "mean_one_way_target_turnover": (
                _mean_float(turnover.get_column("one_way_target_turnover"))
                if not turnover.is_empty()
                else None
            ),
        },
        findings=tuple(findings),
        tables={
            "exposure_reconciliation": frame_records(exposure),
            "cohort_returns": frame_records(cohort_returns),
            "coverage": (
                {
                    "input_bucket_rows": selected_bucket_rows.height,
                    "matched_rows": matched.height,
                    "projected_rows": output.height,
                },
            ),
            "concentration": frame_records(concentration),
            "target_weight_turnover": frame_records(turnover),
            "data_attrition": attrition,
        },
        warnings=(
            "Projection rows are independent diagnostic cohorts; returns are not compounded and "
            "weights are not realized holdings.",
        ),
    )
    return PortfolioProjectionResult(_frame=output, evidence=evidence)


__all__ = ["PortfolioProjectionResult", "portfolio_projection"]
