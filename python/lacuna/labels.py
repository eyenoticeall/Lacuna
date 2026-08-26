"""Forward-return construction with explicit temporal semantics."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, TypeAlias

import polars as pl

from lacuna._attrition import attrition_record
from lacuna._frames import eager_frame, frame_records, validate_panel_schema
from lacuna.exceptions import DataContractError, MethodContractError
from lacuna.types import AnalysisResult, Finding, FindingState, JsonValue, ResultMetadata, Severity

Horizon: TypeAlias = str | int
PriceAdjustment: TypeAlias = Literal["raw", "split_adjusted", "total_return_adjusted", "unknown"]

_HORIZON_PATTERN = re.compile(r"^(?P<count>[1-9][0-9]*)D$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class LabelResult:
    """Typed forward-return frame plus compact construction evidence."""

    _frame: pl.DataFrame
    evidence: AnalysisResult

    @property
    def frame(self) -> pl.DataFrame:
        """Return a shallow clone so callers cannot replace result-owned columns."""

        return self._frame.clone()

    @property
    def metadata(self) -> ResultMetadata:
        """Expose construction provenance."""

        return self.evidence.metadata

    def to_json(self, *, indent: int | None = 2) -> str:
        """Serialize compact evidence; the potentially large label frame stays columnar."""

        return self.evidence.to_json(indent=indent)


def _normalize_horizons(
    horizons: Sequence[Horizon] | None,
    horizon: Horizon | None,
) -> tuple[tuple[str, int], ...]:
    if horizons is not None and horizon is not None:
        raise MethodContractError("pass either horizon or horizons, not both")
    requested: Sequence[Horizon]
    if horizon is not None:
        requested = (horizon,)
    elif horizons is not None:
        requested = horizons
    else:
        raise MethodContractError("at least one forward-return horizon is required")
    if not requested:
        raise MethodContractError("horizons must not be empty")

    normalized: list[tuple[str, int]] = []
    seen: set[str] = set()
    for value in requested:
        if isinstance(value, bool):
            raise MethodContractError("horizons must be positive integers or strings such as '5D'")
        if isinstance(value, int):
            count = value
        elif isinstance(value, str):
            match = _HORIZON_PATTERN.fullmatch(value.strip())
            if match is None:
                raise MethodContractError(
                    f"unsupported horizon {value!r}; v0.1 uses trading-observation "
                    "strings such as '5D'"
                )
            count = int(match.group("count"))
        else:
            raise MethodContractError("horizons must be positive integers or strings such as '5D'")
        if count < 1:
            raise MethodContractError("horizons must be positive")
        name = f"{count}D"
        if name in seen:
            raise MethodContractError(f"duplicate normalized horizon: {name}")
        seen.add(name)
        normalized.append((name, count))
    return tuple(normalized)


def _entry_specification(entry: str | None, price: str) -> tuple[str, int, str]:
    if entry is None:
        return price, 0, "current_price"
    normalized = entry.strip().lower()
    if normalized == "next_open":
        return "open", 1, "next_open"
    if normalized == "next_close":
        return price, 1, "next_close"
    if normalized == "current_close":
        return price, 0, "current_close"
    raise MethodContractError(
        "entry must be one of None, 'current_close', 'next_close', or 'next_open'"
    )


def forward_returns(
    prices: object,
    *,
    schema: Sequence[str] | None = None,
    horizons: Sequence[Horizon] | None = None,
    horizon: Horizon | None = None,
    time: str = "time",
    instrument: str = "instrument",
    price: str = "close",
    signal_time: str | None = None,
    entry: str | None = None,
    exit: str = "close",
    price_adjustment: PriceAdjustment = "unknown",
    delisting_return: str | None = None,
    missing: Literal["drop", "raise"] = "drop",
    allow_same_close: bool = False,
) -> LabelResult:
    """Construct simple forward returns over trading-observation horizons.

    A horizon such as ``"5D"`` means five ordered observations per instrument,
    not five calendar days. The output is long-form and includes observation,
    earning-interval, instrument, horizon, and return columns.
    """

    normalized_horizons = _normalize_horizons(horizons, horizon)
    if missing not in {"drop", "raise"}:
        raise MethodContractError("missing must be 'drop' or 'raise'")
    if price_adjustment not in {
        "raw",
        "split_adjusted",
        "total_return_adjusted",
        "unknown",
    }:
        raise MethodContractError(f"invalid price_adjustment: {price_adjustment!r}")
    entry_column, entry_lag, resolved_entry = _entry_specification(entry, price)
    exit_column = price if exit == "close" else exit
    if signal_time == "close" and entry_lag == 0 and not allow_same_close:
        raise MethodContractError(
            "a close-observed signal cannot use the same close; use entry='next_open' or "
            "entry='next_close', or explicitly set allow_same_close=True"
        )

    required = [time, instrument, entry_column, exit_column]
    if delisting_return is not None:
        required.append(delisting_return)
    frame, diagnostics = eager_frame(prices, schema=schema, required=required)
    numeric_columns = list(dict.fromkeys([entry_column, exit_column]))
    if delisting_return is not None:
        numeric_columns.append(delisting_return)
    validate_panel_schema(
        frame,
        time=time,
        instrument=instrument,
        numeric=numeric_columns,
        name="prices",
    )
    diagnostics = diagnostics.with_execution(
        "validate_price_frame",
        f"sort({instrument},{time})",
        "derive_forward_return_columns",
    )
    infinite_expressions = [
        pl.col(entry_column).is_infinite(),
        pl.col(exit_column).is_infinite(),
    ]
    if delisting_return is not None:
        infinite_expressions.append(pl.col(delisting_return).is_infinite())
    infinite = pl.any_horizontal(infinite_expressions)
    infinite_count = int(frame.select(infinite.sum()).item())
    if infinite_count:
        raise DataContractError(
            f"prices contain {infinite_count} rows with positive or negative infinity"
        )
    source_missing = pl.any_horizontal(
        [
            pl.col(entry_column).is_null() | pl.col(entry_column).is_nan(),
            pl.col(exit_column).is_null() | pl.col(exit_column).is_nan(),
        ]
    )
    source_missing_count = int(frame.select(source_missing.sum()).item())
    if source_missing_count and missing == "raise":
        raise DataContractError(
            f"prices contain {source_missing_count} rows with null or NaN entry/exit values"
        )
    if frame.filter((pl.col(entry_column) <= 0) | (pl.col(exit_column) <= 0)).height:
        raise DataContractError("entry and exit prices must be strictly positive")

    frame = frame.sort([instrument, time])
    label_frames: list[pl.DataFrame] = []
    censored_by_horizon: list[dict[str, object]] = []
    attrition: list[dict[str, JsonValue]] = [
        {
            **attrition_record(
                "source_numeric_eligibility",
                "null_or_nan_entry_or_exit_price",
                input_rows=diagnostics.rows,
                retained_rows=diagnostics.rows - source_missing_count,
                policy=missing,
            ),
            "horizon": None,
        }
    ]
    total_censored = 0
    for name, observations in normalized_horizons:
        if observations < entry_lag:
            raise MethodContractError(
                f"horizon {name} ends before the configured entry observation"
            )
        expressions: list[pl.Expr] = [
            pl.col(time).alias("observation_time"),
            pl.col(time).alias("label_start"),
            pl.col(time).shift(-entry_lag).over(instrument).alias("entry_time"),
            pl.col(time).shift(-observations).over(instrument).alias("label_end"),
            pl.col(instrument).alias("instrument"),
            pl.lit(name).alias("horizon"),
            pl.col(entry_column).shift(-entry_lag).over(instrument).alias("_entry_price"),
            pl.col(exit_column).shift(-observations).over(instrument).alias("_exit_price"),
        ]
        if delisting_return is not None:
            expressions.append(
                pl.col(delisting_return)
                .shift(-observations)
                .over(instrument)
                .alias("_delisting_return")
            )
        candidate = frame.select(expressions)
        direct_return = pl.col("_exit_price") / pl.col("_entry_price") - 1.0
        if delisting_return is not None:
            candidate = candidate.with_columns(
                pl.when(pl.col("_exit_price").is_null())
                .then(pl.col("_delisting_return"))
                .otherwise(direct_return)
                .alias("forward_return")
            )
        else:
            candidate = candidate.with_columns(direct_return.alias("forward_return"))

        invalid = pl.any_horizontal(
            [
                pl.col("label_start").is_null(),
                pl.col("entry_time").is_null(),
                pl.col("label_end").is_null(),
                pl.col("_entry_price").is_null() | pl.col("_entry_price").is_nan(),
                pl.col("forward_return").is_null() | pl.col("forward_return").is_nan(),
            ]
        )
        censored = int(candidate.select(invalid.sum()).item())
        total_censored += censored
        if censored and missing == "raise":
            raise DataContractError(
                f"horizon {name} has {censored} rows without an entry or exit observation"
            )
        candidate = candidate.filter(~invalid).select(
            "observation_time",
            "label_start",
            "entry_time",
            "label_end",
            "instrument",
            "horizon",
            "forward_return",
        )
        label_frames.append(candidate)
        censored_by_horizon.append(
            {
                "horizon": name,
                "eligible_rows": candidate.height,
                "censored_rows": censored,
            }
        )
        attrition.append(
            {
                **attrition_record(
                    "horizon_eligibility",
                    "missing_entry_exit_or_label_boundary",
                    input_rows=diagnostics.rows,
                    retained_rows=candidate.height,
                    policy=missing,
                ),
                "horizon": name,
            }
        )

    labels = pl.concat(label_frames, how="vertical").sort(
        ["horizon", "observation_time", "instrument"]
    )
    if labels.is_empty():
        raise DataContractError("no forward returns remain after applying the missing-data policy")

    findings: list[Finding] = []
    if price_adjustment == "unknown":
        findings.append(
            Finding(
                code="PRICE_ADJUSTMENT_UNKNOWN",
                title="Price adjustment is unknown",
                message=(
                    "Forward returns may be distorted by splits, dividends, or other "
                    "corporate actions."
                ),
                state=FindingState.UNKNOWN,
                severity=Severity.HIGH,
                category="data_integrity",
            )
        )
    if delisting_return is None:
        findings.append(
            Finding(
                code="DELISTING_RETURNS_UNKNOWN",
                title="Delisting return handling is unknown",
                message="The supplied prices do not declare a delisting-return field.",
                state=FindingState.UNKNOWN,
                severity=Severity.HIGH,
                category="data_integrity",
            )
        )

    coverage = pl.DataFrame(censored_by_horizon)
    evidence = AnalysisResult(
        metadata=ResultMetadata(
            method="labels.forward_returns",
            method_version=1,
            parameters={
                "horizons": tuple(name for name, _ in normalized_horizons),
                "input_schema": tuple(schema) if schema is not None else None,
                "horizon_clock": "trading_observations",
                "time_column": time,
                "instrument_column": instrument,
                "entry": resolved_entry,
                "entry_column": entry_column,
                "exit_column": exit_column,
                "signal_time": signal_time,
                "price_adjustment": price_adjustment,
                "delisting_return_column": delisting_return,
                "missing_policy": missing,
                "interval_closure": "[label_start, label_end)",
                "input": diagnostics.to_parameters(),
            },
        ),
        metrics={
            "n_labels": labels.height,
            "n_instruments": labels.get_column("instrument").n_unique(),
            "n_horizons": len(normalized_horizons),
            "source_missing_rows": source_missing_count,
            "censored_rows": total_censored,
        },
        findings=tuple(findings),
        tables={
            "coverage_by_horizon": frame_records(coverage),
            "data_attrition": tuple(attrition),
        },
    )
    return LabelResult(_frame=labels, evidence=evidence)


__all__ = ["Horizon", "LabelResult", "PriceAdjustment", "forward_returns"]
