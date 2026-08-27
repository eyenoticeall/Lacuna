"""Availability-anchored event windows and dependence-aware response inference."""

from __future__ import annotations

import math
import secrets
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal, TypeAlias

import numpy as np
import numpy.typing as npt
import polars as pl

from lacuna._attrition import attrition_record
from lacuna._frames import (
    eager_frame,
    frame_records,
    require_compatible_keys,
    require_identifier,
    require_no_nulls,
    require_time_key,
    require_unique,
    validate_panel_schema,
)
from lacuna._resampling import stationary_bootstrap_indices
from lacuna.exceptions import DataContractError, MethodContractError
from lacuna.types import AnalysisResult, Finding, FindingState, JsonValue, ResultMetadata, Severity

FloatArray: TypeAlias = npt.NDArray[np.float64]
AnchorPolicy = Literal["available_time", "event_time"]
OverlapPolicy = Literal["raise", "keep"]


@dataclass(frozen=True, slots=True)
class EventWindowResult:
    """Immutable event-path rows plus alignment and coverage evidence."""

    _frame: pl.DataFrame
    evidence: AnalysisResult

    @property
    def frame(self) -> pl.DataFrame:
        """Return a shallow clone of result-owned event rows."""

        return self._frame.clone()

    @property
    def metadata(self) -> ResultMetadata:
        """Expose window-construction provenance."""

        return self.evidence.metadata

    def to_json(self, *, indent: int | None = 2) -> str:
        """Serialize compact evidence without embedding every event path row."""

        return self.evidence.to_json(indent=indent)


def _delay(later: object, earlier: object) -> float | None:
    if isinstance(later, datetime | date) and isinstance(earlier, datetime | date):
        difference = later - earlier
        if isinstance(difference, timedelta):
            return difference.total_seconds()
    if (
        isinstance(later, int | float)
        and not isinstance(later, bool)
        and isinstance(earlier, int | float)
        and not isinstance(earlier, bool)
    ):
        return float(later) - float(earlier)
    return None


def _integer(value: object, *, name: str) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise MethodContractError(f"{name} must be an integer")


def _window_clusters(windows: list[dict[str, object]]) -> tuple[dict[object, str], int]:
    assignments: dict[object, str] = {}
    overlap_events: set[object] = set()
    cluster_counter = 0
    by_instrument: dict[object, list[dict[str, object]]] = {}
    for window in windows:
        by_instrument.setdefault(window["instrument"], []).append(window)
    for instrument_windows in by_instrument.values():
        ordered = sorted(
            instrument_windows,
            key=lambda row: (
                _integer(row["window_start_index"], name="window_start_index"),
                str(row["event_id"]),
            ),
        )
        cluster: list[dict[str, object]] = []
        cluster_end: int | None = None
        for window in ordered:
            start = _integer(window["window_start_index"], name="window_start_index")
            end = _integer(window["window_end_index"], name="window_end_index")
            if cluster_end is None or start > cluster_end:
                if cluster:
                    cluster_counter += 1
                    identity = f"overlap-{cluster_counter:04d}"
                    for member in cluster:
                        assignments[member["event_id"]] = identity
                    if len(cluster) > 1:
                        overlap_events.update(member["event_id"] for member in cluster)
                cluster = [window]
                cluster_end = end
            else:
                cluster.append(window)
                cluster_end = max(cluster_end, end)
        if cluster:
            cluster_counter += 1
            identity = f"overlap-{cluster_counter:04d}"
            for member in cluster:
                assignments[member["event_id"]] = identity
            if len(cluster) > 1:
                overlap_events.update(member["event_id"] for member in cluster)
    return assignments, len(overlap_events)


def event_windows(
    events: object,
    prices: object,
    *,
    event_id: str = "event_id",
    instrument: str = "instrument",
    event_time: str = "event_time",
    available_time: str = "available_time",
    price_time: str = "time",
    price: str = "close",
    anchor: AnchorPolicy = "available_time",
    before: int = 5,
    after: int = 10,
    alignment: Literal["next_observation"] = "next_observation",
    overlap_policy: OverlapPolicy = "raise",
    price_adjustment: str = "unknown",
) -> EventWindowResult:
    """Align events to the first price observation at or after an explicit anchor."""

    if anchor not in {"available_time", "event_time"}:
        raise MethodContractError("anchor must be 'available_time' or 'event_time'")
    if alignment != "next_observation":
        raise MethodContractError("alignment must be 'next_observation'")
    if overlap_policy not in {"raise", "keep"}:
        raise MethodContractError("overlap_policy must be 'raise' or 'keep'")
    if (
        isinstance(before, bool)
        or not isinstance(before, int)
        or before < 0
        or isinstance(after, bool)
        or not isinstance(after, int)
        or after < 0
    ):
        raise MethodContractError("before and after must be non-negative integers")
    if not isinstance(price_adjustment, str) or not price_adjustment:
        raise MethodContractError("price_adjustment must be a non-empty declaration")

    event_frame, event_diagnostics = eager_frame(
        events,
        required=(event_id, instrument, event_time, available_time),
    )
    if event_frame.is_empty():
        raise DataContractError("events must contain at least one row")
    require_no_nulls(
        event_frame,
        [event_id, instrument, event_time, available_time],
        name="events",
    )
    require_identifier(event_frame, event_id, name="events")
    require_identifier(event_frame, instrument, name="events")
    require_time_key(event_frame, event_time, name="events")
    require_time_key(event_frame, available_time, name="events")
    require_compatible_keys(
        event_frame,
        event_frame,
        pairs=((event_time, available_time),),
    )
    require_unique(event_frame, [event_id], name="events")

    price_frame, price_diagnostics = eager_frame(
        prices,
        required=(price_time, instrument, price),
    )
    validate_panel_schema(
        price_frame,
        time=price_time,
        instrument=instrument,
        numeric=[price],
        name="prices",
    )
    require_compatible_keys(
        event_frame,
        price_frame,
        pairs=((event_time, price_time), (instrument, instrument)),
    )
    invalid_price = price_frame.filter(
        pl.col(price).is_not_null()
        & (pl.col(price).is_nan() | pl.col(price).is_infinite() | (pl.col(price) <= 0.0))
    ).height
    if invalid_price:
        raise DataContractError(
            f"prices contain {invalid_price} non-positive or non-finite observed values"
        )
    indexed_prices = (
        price_frame.select(
            pl.col(instrument).alias("_instrument"),
            pl.col(price_time).alias("_price_time"),
            pl.col(price).cast(pl.Float64).alias("_price"),
        )
        .sort(["_instrument", "_price_time"])
        .with_columns(
            pl.int_range(pl.len()).over("_instrument").cast(pl.Int64).alias("_price_index"),
            pl.len().over("_instrument").cast(pl.Int64).alias("_price_count"),
        )
    )
    price_counts = indexed_prices.group_by("_instrument", maintain_order=True).agg(
        pl.col("_price_count").first()
    )
    ordered_events = (
        event_frame.select(
            pl.col(event_id).alias("_event_id"),
            pl.col(instrument).alias("_instrument"),
            pl.col(event_time).alias("_event_time"),
            pl.col(available_time).alias("_available_time"),
        )
        .sort(["_event_time", "_event_id"])
        .with_row_index("_event_order")
        .with_columns(
            pl.col("_available_time" if anchor == "available_time" else "_event_time").alias(
                "_anchor_time"
            )
        )
        .join(price_counts, on="_instrument", how="left", maintain_order="left")
    )
    first_observations = indexed_prices.select(
        "_instrument",
        pl.col("_price_time").alias("_first_observation_time"),
        pl.col("_price_index").alias("_first_observation_index"),
    ).sort("_first_observation_time")
    eligible_anchors = (
        indexed_prices.filter(pl.col("_price").is_not_null())
        .select(
            "_instrument",
            pl.col("_price_time").alias("_aligned_anchor_time"),
            pl.col("_price_index").alias("_anchor_index"),
            pl.col("_price").alias("_anchor_price"),
        )
        .sort("_aligned_anchor_time")
    )
    aligned = (
        ordered_events.sort("_anchor_time")
        .join_asof(
            first_observations,
            left_on="_anchor_time",
            right_on="_first_observation_time",
            by="_instrument",
            strategy="forward",
            check_sortedness=False,
        )
        .join_asof(
            eligible_anchors,
            left_on="_anchor_time",
            right_on="_aligned_anchor_time",
            by="_instrument",
            strategy="forward",
            check_sortedness=False,
        )
        .with_columns(
            pl.when(pl.col("_first_observation_index").is_null())
            .then(0)
            .otherwise(
                pl.coalesce("_anchor_index", "_price_count") - pl.col("_first_observation_index")
            )
            .cast(pl.Int64)
            .alias("_skipped_anchor_prices")
        )
        .sort("_event_order")
    )
    aligned_only = aligned.filter(pl.col("_anchor_index").is_not_null())
    offset_frame = pl.DataFrame({"offset": range(-before, after + 1)})
    expanded_paths = (
        aligned_only.join(offset_frame, how="cross")
        .with_columns((pl.col("_anchor_index") + pl.col("offset")).alias("_path_index"))
        .join(
            indexed_prices.select(
                "_instrument",
                "_price_index",
                "_price_time",
                "_price",
            ),
            left_on=("_instrument", "_path_index"),
            right_on=("_instrument", "_price_index"),
            how="left",
            maintain_order="left",
        )
        .with_columns(
            ((pl.col("_path_index") >= 0) & (pl.col("_path_index") < pl.col("_price_count"))).alias(
                "_in_bounds"
            )
        )
    )
    path_coverage = (
        expanded_paths.filter(pl.col("_in_bounds"))
        .group_by("_event_id", maintain_order=True)
        .agg(
            pl.col("_price").is_not_null().sum().cast(pl.Int64).alias("_observed_rows"),
            pl.col("_price").is_null().sum().cast(pl.Int64).alias("_missing_price_rows"),
        )
    )
    aligned = aligned.join(path_coverage, on="_event_id", how="left", maintain_order="left")
    output = (
        expanded_paths.filter(pl.col("_in_bounds") & pl.col("_price").is_not_null())
        .select(
            pl.col("_event_id").alias("event_id"),
            pl.col("_instrument").alias("instrument"),
            pl.col("_event_time").alias("event_time"),
            pl.col("_available_time").alias("available_time"),
            pl.col("_anchor_time").alias("anchor_time"),
            pl.col("_aligned_anchor_time").alias("aligned_anchor_time"),
            "offset",
            pl.col("_price_time").alias("price_time"),
            pl.col("_price").alias("price"),
            pl.col("_anchor_price").alias("anchor_price"),
            (pl.col("_price") / pl.col("_anchor_price") - 1.0).alias("response"),
        )
        .sort(["aligned_anchor_time", "event_id", "offset"])
    )
    if output.is_empty():
        raise DataContractError("no event window observations remain after anchor alignment")

    coverage_rows: list[dict[str, object]] = []
    window_descriptors: list[dict[str, object]] = []
    aligned_events = aligned_only.height
    retrospective_lookahead = (
        int(event_frame.select((pl.col(available_time) > pl.col(event_time)).sum()).item())
        if anchor == "event_time"
        else 0
    )
    skipped_anchor_prices = int(aligned.get_column("_skipped_anchor_prices").sum() or 0)
    expected_rows = before + after + 1
    for event in aligned.to_dicts():
        event_identity = event["_event_id"]
        instrument_identity = event["_instrument"]
        price_count = event["_price_count"]
        anchor_index = event["_anchor_index"]
        if price_count is None:
            coverage_rows.append(
                {
                    "event_id": event_identity,
                    "instrument": instrument_identity,
                    "expected_rows": expected_rows,
                    "observed_rows": 0,
                    "censored_rows": expected_rows,
                    "left_censored_rows": before,
                    "right_censored_rows": after + 1,
                    "missing_price_rows": 0,
                    "anchor_delay": None,
                    "status": "no_instrument_prices",
                }
            )
            continue
        if anchor_index is None:
            coverage_rows.append(
                {
                    "event_id": event_identity,
                    "instrument": instrument_identity,
                    "expected_rows": expected_rows,
                    "observed_rows": 0,
                    "censored_rows": expected_rows,
                    "left_censored_rows": before,
                    "right_censored_rows": after + 1,
                    "missing_price_rows": 0,
                    "anchor_delay": None,
                    "status": "no_eligible_anchor",
                }
            )
            continue
        resolved_anchor_index = _integer(anchor_index, name="anchor_index")
        resolved_price_count = _integer(price_count, name="price_count")
        left_censored = max(0, before - resolved_anchor_index)
        right_censored = max(
            0,
            resolved_anchor_index + after - (resolved_price_count - 1),
        )
        observed_rows = _integer(event["_observed_rows"], name="observed_rows")
        missing_prices = _integer(event["_missing_price_rows"], name="missing_price_rows")
        coverage_rows.append(
            {
                "event_id": event_identity,
                "instrument": instrument_identity,
                "expected_rows": expected_rows,
                "observed_rows": observed_rows,
                "censored_rows": expected_rows - observed_rows,
                "left_censored_rows": left_censored,
                "right_censored_rows": right_censored,
                "missing_price_rows": missing_prices,
                "anchor_delay": _delay(event["_aligned_anchor_time"], event["_anchor_time"]),
                "status": "aligned",
            }
        )
        window_descriptors.append(
            {
                "event_id": event_identity,
                "instrument": instrument_identity,
                "window_start_index": resolved_anchor_index - before,
                "window_end_index": resolved_anchor_index + after,
            }
        )
    clusters, overlapping_events = _window_clusters(window_descriptors)
    if overlapping_events and overlap_policy == "raise":
        raise DataContractError(
            f"{overlapping_events} events have overlapping same-instrument windows"
        )
    cluster_frame = pl.DataFrame(
        {
            "event_id": list(clusters),
            "overlap_cluster": list(clusters.values()),
        }
    )
    output = output.join(cluster_frame, on="event_id", how="left", maintain_order="left")
    coverage = pl.DataFrame(coverage_rows).sort("event_id")
    findings: list[Finding] = []
    if retrospective_lookahead:
        findings.append(
            Finding(
                code="EVENT_RETROSPECTIVE_ANCHOR_LOOKAHEAD",
                title="Retrospective event-time anchoring precedes availability",
                message="Some event paths begin before the event was available to a decision.",
                state=FindingState.WARN,
                severity=Severity.HIGH,
                category="temporal_integrity",
                evidence={"events": retrospective_lookahead},
            )
        )
    if overlapping_events:
        findings.append(
            Finding(
                code="EVENT_WINDOWS_OVERLAP",
                title="Same-instrument event windows overlap",
                message="Explicit retention preserves overlap clusters for dependent inference.",
                state=FindingState.WARN,
                severity=Severity.MEDIUM,
                category="statistical_validity",
                evidence={"events": overlapping_events},
            )
        )
    censored_events = int(coverage.filter(pl.col("censored_rows") > 0).height)
    if censored_events:
        findings.append(
            Finding(
                code="EVENT_WINDOWS_CENSORED",
                title="Some event windows are incomplete",
                message="Boundary or missing-price censoring reduced one or more event paths.",
                state=FindingState.WARN,
                severity=Severity.MEDIUM,
                category="data_integrity",
                evidence={"events": censored_events},
            )
        )
    if price_adjustment == "unknown":
        findings.append(
            Finding(
                code="EVENT_PRICE_ADJUSTMENT_UNKNOWN",
                title="Event-study price adjustment is unknown",
                message="Corporate actions may distort raw price-relative event paths.",
                state=FindingState.UNKNOWN,
                severity=Severity.HIGH,
                category="data_integrity",
            )
        )
    expected_observations = aligned_events * (before + after + 1)
    attrition: tuple[JsonValue, ...] = (
        attrition_record(
            "event_alignment",
            "no_instrument_price_or_eligible_anchor",
            input_rows=event_frame.height,
            retained_rows=aligned_events,
            policy="retain_covered_events",
        ),
        attrition_record(
            "window_observations",
            "boundary_censoring_or_missing_price",
            input_rows=expected_observations,
            retained_rows=output.height,
            policy="retain_partial_paths",
        ),
    )
    evidence = AnalysisResult(
        metadata=ResultMetadata(
            method="events.event_windows",
            method_version=1,
            parameters={
                "event_id": event_id,
                "instrument": instrument,
                "event_time": event_time,
                "available_time": available_time,
                "price_time": price_time,
                "price": price,
                "anchor": anchor,
                "before": before,
                "after": after,
                "offset_interval": (-before, after + 1),
                "offset_interval_closure": "[-before, after+1)",
                "alignment": alignment,
                "overlap_policy": overlap_policy,
                "price_adjustment": price_adjustment,
                "event_input": event_diagnostics.to_parameters(),
                "price_input": price_diagnostics.to_parameters(),
            },
        ),
        metrics={
            "n_events": event_frame.height,
            "aligned_events": aligned_events,
            "n_window_rows": output.height,
            "censored_events": censored_events,
            "overlapping_events": overlapping_events,
            "retrospective_lookahead_events": retrospective_lookahead,
            "skipped_null_anchor_prices": skipped_anchor_prices,
        },
        findings=tuple(findings),
        tables={
            "event_coverage": frame_records(coverage),
            "data_attrition": attrition,
        },
    )
    return EventWindowResult(_frame=output, evidence=evidence)


def event_response(
    windows: EventWindowResult,
    *,
    confidence: float = 0.95,
    resamples: int = 2_000,
    expected_block_length: float | None = None,
    seed: int | None = None,
    min_clusters: int = 20,
) -> AnalysisResult:
    """Estimate event response with stationary bootstrap over anchor-time clusters."""

    if (
        not isinstance(windows, EventWindowResult)
        or windows.metadata.method != "events.event_windows"
    ):
        raise MethodContractError("windows must be an EventWindowResult from event_windows")
    if not 0.0 < confidence < 1.0:
        raise MethodContractError("confidence must be between zero and one")
    if resamples < 100:
        raise MethodContractError("resamples must be at least 100")
    if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int) or seed < 0):
        raise MethodContractError("seed must be a non-negative integer")
    if isinstance(min_clusters, bool) or not isinstance(min_clusters, int) or min_clusters < 2:
        raise MethodContractError("min_clusters must be an integer of at least two")

    frame = windows.frame
    descriptive = (
        frame.group_by("offset", maintain_order=True)
        .agg(
            pl.col("response").mean().alias("mean_response"),
            pl.len().alias("n_events"),
        )
        .sort("offset")
    )
    expected_offsets = tuple(
        range(
            -_integer(windows.metadata.parameters["before"], name="before"),
            _integer(windows.metadata.parameters["after"], name="after") + 1,
        )
    )
    complete_paths: list[tuple[object, FloatArray]] = []
    for path in frame.partition_by("event_id", maintain_order=True):
        ordered = path.sort("offset")
        if tuple(ordered.get_column("offset")) != expected_offsets:
            continue
        complete_paths.append(
            (
                ordered.get_column("aligned_anchor_time")[0],
                ordered.get_column("response").to_numpy().astype(np.float64, copy=False),
            )
        )
    clusters: dict[object, list[FloatArray]] = {}
    for anchor_time, path in complete_paths:
        clusters.setdefault(anchor_time, []).append(path)
    cluster_paths = [np.stack(paths) for paths in clusters.values()]
    n_clusters = len(cluster_paths)
    n_complete = len(complete_paths)
    input_events = frame.get_column("event_id").n_unique()
    block_length = (
        max(2.0, round(n_clusters ** (1.0 / 3.0)))
        if expected_block_length is None
        else float(expected_block_length)
    )
    if not math.isfinite(block_length) or block_length < 1.0:
        raise MethodContractError("expected_block_length must be finite and at least one")

    descriptive_rows = descriptive.to_dicts()
    if n_clusters < min_clusters or n_complete == 0:
        response_rows: tuple[JsonValue, ...] = tuple(
            {
                **row,
                "inference_mean": None,
                "pointwise_lower": None,
                "pointwise_upper": None,
                "simultaneous_lower": None,
                "simultaneous_upper": None,
                "n_complete_events": n_complete,
                "n_clusters": n_clusters,
            }
            for row in descriptive_rows
        )
        return AnalysisResult(
            metadata=ResultMetadata(
                method="events.event_response",
                method_version=1,
                parameters={
                    "source_method": windows.metadata.method,
                    "confidence": confidence,
                    "resamples": resamples,
                    "expected_block_length": block_length,
                    "seed": seed,
                    "min_clusters": min_clusters,
                    "resampling_unit": "ordered_anchor_time_cluster_complete_paths",
                },
            ),
            metrics={
                "n_events": input_events,
                "n_complete_events": n_complete,
                "n_clusters": n_clusters,
                "successful_resamples": 0,
            },
            findings=(
                Finding(
                    code="EVENT_INFERENCE_SUPPORT_INSUFFICIENT",
                    title="Event response inference is unavailable",
                    message="Fewer than the required complete anchor-time clusters are available.",
                    state=FindingState.UNKNOWN,
                    severity=Severity.HIGH,
                    category="statistical_validity",
                    evidence={"n_clusters": n_clusters, "minimum": min_clusters},
                ),
            ),
            tables={
                "event_response": response_rows,
                "data_attrition": (
                    attrition_record(
                        "complete_path_inference",
                        "censored_event_path",
                        input_rows=input_events,
                        retained_rows=n_complete,
                        policy="descriptive_only_when_incomplete",
                    ),
                ),
            },
        )

    root_entropy = seed if seed is not None else secrets.randbits(128)
    child = np.random.SeedSequence(root_entropy).spawn(1)[0]
    rng = np.random.default_rng(child)
    indices = stationary_bootstrap_indices(
        n_clusters,
        resamples=resamples,
        expected_block_length=block_length,
        rng=rng,
    )
    complete_matrix: FloatArray = np.concatenate(cluster_paths, axis=0)
    center: FloatArray = complete_matrix.mean(axis=0)
    bootstrap: FloatArray = np.empty((resamples, len(expected_offsets)), dtype=np.float64)
    for replicate, sample in enumerate(indices):
        bootstrap[replicate] = np.concatenate(
            [cluster_paths[int(index)] for index in sample], axis=0
        ).mean(axis=0)
    alpha = 1.0 - confidence
    pointwise: FloatArray = np.quantile(bootstrap, [alpha / 2.0, 1.0 - alpha / 2.0], axis=0)
    deviations: FloatArray = bootstrap.std(axis=0, ddof=1)
    zero_tolerance = np.finfo(np.float64).eps * np.maximum(1.0, np.abs(center)) * 16.0
    defined = deviations > zero_tolerance
    if bool(defined.any()):
        standardized = np.abs((bootstrap[:, defined] - center[defined]) / deviations[defined])
        critical = float(np.quantile(standardized.max(axis=1), confidence))
    else:
        critical = math.nan
    descriptive_by_offset = {int(row["offset"]): row for row in descriptive_rows}
    response_rows_list: list[JsonValue] = []
    for index, offset in enumerate(expected_offsets):
        row = descriptive_by_offset[offset]
        simultaneous_lower = (
            float(center[index] - critical * deviations[index]) if defined[index] else None
        )
        simultaneous_upper = (
            float(center[index] + critical * deviations[index]) if defined[index] else None
        )
        response_rows_list.append(
            {
                **row,
                "inference_mean": float(center[index]),
                "pointwise_lower": float(pointwise[0, index]),
                "pointwise_upper": float(pointwise[1, index]),
                "simultaneous_lower": simultaneous_lower,
                "simultaneous_upper": simultaneous_upper,
                "n_complete_events": n_complete,
                "n_clusters": n_clusters,
            }
        )
    negative = [
        float(row["mean_response"])
        for row in descriptive_rows
        if int(row["offset"]) < 0 and isinstance(row["mean_response"], int | float)
    ]
    pre_event_mean = float(np.mean(negative)) if negative else None
    pre_event_max = max((abs(value) for value in negative), default=None)
    return AnalysisResult(
        metadata=ResultMetadata(
            method="events.event_response",
            method_version=1,
            parameters={
                "source_method": windows.metadata.method,
                "confidence": confidence,
                "resamples": resamples,
                "expected_block_length": block_length,
                "seed": seed,
                "root_entropy": root_entropy,
                "substream_identity": "SeedSequence(root_entropy).spawn(1)[0]",
                "min_clusters": min_clusters,
                "resampling_unit": "ordered_anchor_time_cluster_complete_paths",
                "pointwise_interval": "percentile",
                "simultaneous_band": "max_standardized_deviation",
            },
        ),
        metrics={
            "n_events": input_events,
            "n_complete_events": n_complete,
            "n_clusters": n_clusters,
            "successful_resamples": resamples,
            "simultaneous_critical_value": critical if math.isfinite(critical) else None,
            "pre_event_mean_response": pre_event_mean,
            "pre_event_max_absolute_mean": pre_event_max,
        },
        findings=(
            Finding(
                code="EVENT_CLUSTERED_INFERENCE_AVAILABLE",
                title="Clustered complete-path event inference is available",
                message="Pointwise and simultaneous bands use ordered anchor-time cluster blocks.",
                state=FindingState.PASS,
                severity=Severity.INFO,
                category="statistical_validity",
                evidence={"n_clusters": n_clusters, "n_complete_events": n_complete},
            ),
        ),
        tables={
            "event_response": tuple(response_rows_list),
            "data_attrition": (
                attrition_record(
                    "complete_path_inference",
                    "censored_event_path",
                    input_rows=input_events,
                    retained_rows=n_complete,
                    policy="complete_paths_only",
                ),
            ),
        },
    )


__all__ = ["EventWindowResult", "event_response", "event_windows"]
