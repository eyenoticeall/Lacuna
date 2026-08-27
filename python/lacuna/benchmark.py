"""Reproducible developer benchmarks for Lacuna's public analytical workflows."""

from __future__ import annotations

import gc
import hashlib
import json
import math
import platform
import statistics
import sys
import time
import tracemalloc
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TypeAlias

import numpy as np
import numpy.typing as npt
import polars as pl

from lacuna import bias, costs, events, signal
from lacuna.adapters import (
    AdaptedFrame,
    BacktestSchema,
    BacktestSemantics,
    FactorPanelSchema,
    FactorPanelSemantics,
    VendorSchema,
    adapt_backtest,
    adapt_factor_panel,
    adapt_vendor,
)
from lacuna.audit_profiles import standard_audit
from lacuna.bias import PointInTimeJoinResult
from lacuna.cv import CombinatorialPurgedKFold, CombinatorialSplitResult, PurgedKFold, SplitResult
from lacuna.events import EventWindowResult
from lacuna.exceptions import MethodContractError
from lacuna.labels import LabelResult, forward_returns
from lacuna.native import native_status
from lacuna.report import AuditReport
from lacuna.signal import PortfolioProjectionResult, SignalTransformResult
from lacuna.study import SignalStudy
from lacuna.types import AnalysisResult
from lacuna.validation import (
    bootstrap,
    permutation_test,
    probability_of_backtest_overfitting,
    reality_check,
    superior_predictive_ability,
)

BenchmarkOutput: TypeAlias = (
    AnalysisResult
    | AuditReport
    | AdaptedFrame
    | CombinatorialSplitResult
    | EventWindowResult
    | LabelResult
    | PointInTimeJoinResult
    | PortfolioProjectionResult
    | SignalTransformResult
    | SplitResult
)
BenchmarkCallable: TypeAlias = Callable[[], BenchmarkOutput]
IntArray: TypeAlias = npt.NDArray[np.int64]
_PRIVATE_MIGRATION_COST_CASES = {
    "migration.costs.break_even.public",
    "migration.costs.capacity.public",
    "migration.costs.stress.public",
}
_PRIVATE_MIGRATION_VALIDATION_CASES = {
    "migration.validation.permutation.public",
}


@dataclass(frozen=True, slots=True)
class BenchmarkConfig:
    """Deterministic dataset and measurement configuration."""

    periods: int = 40
    instruments: int = 100
    horizons: tuple[int, ...] = (1, 5, 20)
    quantiles: int = 5
    bootstrap_resamples: int = 200
    repetitions: int = 3
    warmups: int = 1
    seed: int = 42

    def __post_init__(self) -> None:
        if self.periods < 3 or self.instruments < 3:
            raise MethodContractError("benchmarks require at least 3 periods and 3 instruments")
        if not self.horizons or any(horizon < 1 for horizon in self.horizons):
            raise MethodContractError("benchmark horizons must be positive")
        if len(self.horizons) != len(set(self.horizons)):
            raise MethodContractError("benchmark horizons must be unique")
        if max(self.horizons) >= self.periods:
            raise MethodContractError("benchmark horizons must be shorter than the panel")
        if not 2 <= self.quantiles <= self.instruments:
            raise MethodContractError("benchmark quantiles must be between 2 and instruments")
        if self.bootstrap_resamples < 100:
            raise MethodContractError("benchmark bootstrap_resamples must be at least 100")
        if self.repetitions < 1 or self.warmups < 0:
            raise MethodContractError(
                "benchmark repetitions must be positive and warmups non-negative"
            )
        if self.seed < 0:
            raise MethodContractError("benchmark seed must be non-negative")

    @property
    def rows(self) -> int:
        """Return rows in each generated panel."""

        return self.periods * self.instruments

    @property
    def horizon_names(self) -> tuple[str, ...]:
        """Return public trading-observation horizon names."""

        return tuple(f"{horizon}D" for horizon in self.horizons)

    def to_dict(self) -> dict[str, object]:
        """Return JSON-compatible resolved configuration."""

        return {
            "periods": self.periods,
            "instruments": self.instruments,
            "rows": self.rows,
            "horizons": list(self.horizon_names),
            "quantiles": self.quantiles,
            "bootstrap_resamples": self.bootstrap_resamples,
            "repetitions": self.repetitions,
            "warmups": self.warmups,
            "seed": self.seed,
        }


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    """One measured public operation with an equivalence checksum."""

    name: str
    backend: str
    median_seconds: float
    minimum_seconds: float
    maximum_seconds: float
    throughput: float
    throughput_unit: str
    python_traced_peak_bytes: int
    checksum: str

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible measurement record."""

        return {
            "name": self.name,
            "backend": self.backend,
            "median_seconds": self.median_seconds,
            "minimum_seconds": self.minimum_seconds,
            "maximum_seconds": self.maximum_seconds,
            "throughput": self.throughput,
            "throughput_unit": self.throughput_unit,
            "python_traced_peak_bytes": self.python_traced_peak_bytes,
            "checksum": self.checksum,
        }


@dataclass(frozen=True, slots=True)
class BenchmarkSuite:
    """Versioned benchmark artifact; timings are environment-specific evidence."""

    config: BenchmarkConfig
    cases: tuple[BenchmarkCase, ...]
    generated_at: datetime
    environment: Mapping[str, object]
    schema_version: str = "1"
    benchmark_version: int = 6

    def to_dict(self) -> dict[str, object]:
        """Return the complete benchmark artifact."""

        return {
            "schema_version": self.schema_version,
            "benchmark_version": self.benchmark_version,
            "generated_at": self.generated_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "config": self.config.to_dict(),
            "environment": dict(self.environment),
            "cases": [case.to_dict() for case in self.cases],
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        """Serialize with stable key ordering."""

        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)


@dataclass(frozen=True, slots=True)
class _BenchmarkTrace:
    """Private raw measurement evidence used by the migration sidecar."""

    name: str
    timings_seconds: tuple[float, ...]
    baseline_rss_bytes: int | None
    process_peak_rss_bytes: int | None
    incremental_peak_rss_bytes: int | None
    python_traced_peak_bytes: int


def benchmark_config_for_tier(
    tier: str,
    *,
    repetitions: int = 3,
    warmups: int = 1,
    seed: int = 42,
) -> BenchmarkConfig:
    """Resolve the committed smoke/small/medium benchmark tiers."""

    sizes = {
        "smoke": (40, 100, 200),
        "small": (200, 500, 1_000),
        "medium": (1_000, 5_000, 2_000),
    }
    try:
        periods, instruments, resamples = sizes[tier]
    except KeyError as error:
        raise MethodContractError("benchmark tier must be smoke, small, or medium") from error
    return BenchmarkConfig(
        periods=periods,
        instruments=instruments,
        bootstrap_resamples=resamples,
        repetitions=repetitions,
        warmups=warmups,
        seed=seed,
    )


def _panels(config: BenchmarkConfig) -> tuple[pl.DataFrame, pl.DataFrame]:
    times_by_instrument = np.tile(np.arange(config.periods, dtype=np.int64), config.instruments)
    instruments_by_time = np.tile(np.arange(config.instruments, dtype=np.int64), config.periods)
    instrument_blocks: IntArray = np.repeat(
        np.arange(config.instruments, dtype=np.int64), config.periods
    )
    times_by_period: IntArray = np.repeat(
        np.arange(config.periods, dtype=np.int64), config.instruments
    )
    rates = 0.000_01 + 0.000_5 * instrument_blocks / max(config.instruments - 1, 1)
    prices = pl.DataFrame(
        {
            "time": times_by_instrument,
            "instrument": instrument_blocks,
            "close": 100.0 * np.exp(rates * times_by_instrument),
        }
    )
    signal_values = instruments_by_time.astype(np.float64) + 0.01 * np.sin(times_by_period)
    observations = pl.DataFrame(
        {
            "time": times_by_period,
            "instrument": instruments_by_time,
            "signal": signal_values,
        }
    )
    return observations, prices


def _trades(config: BenchmarkConfig) -> pl.DataFrame:
    """Generate a deterministic normalized trade panel for cost-grid measurement."""

    periods: IntArray = np.repeat(np.arange(config.periods, dtype=np.int64), config.instruments)
    instruments: IntArray = np.tile(np.arange(config.instruments, dtype=np.int64), config.periods)
    buy = instruments % 2 == 0
    absolute_quantity = 100.0 + instruments.astype(np.float64)
    quantity = np.where(buy, absolute_quantity, -absolute_quantity)
    price = 50.0 + instruments.astype(np.float64) / max(config.instruments, 1)
    gross_pnl = 0.002 * absolute_quantity * price * np.sin(periods + 1.0)
    return pl.DataFrame(
        {
            "decision_time": periods,
            "execution_time": periods,
            "instrument": instruments,
            "side": np.where(buy, "buy", "sell"),
            "quantity": quantity,
            "price": price,
            "reference_price": price,
            "gross_pnl": gross_pnl,
        }
    )


def _without_created_at(result: AnalysisResult) -> dict[str, object]:
    payload = result.to_dict()
    metadata = payload["metadata"]
    assert isinstance(metadata, dict)
    metadata.pop("created_at")
    return payload


def _output_payload(output: BenchmarkOutput) -> tuple[dict[str, object], str]:
    if isinstance(output, AuditReport):
        result = output.result
        return _without_created_at(result), "workflow"
    if isinstance(output, LabelResult):
        frame = output.frame
        summary = frame.select(
            pl.len().alias("rows"),
            pl.col("forward_return").sum().alias("return_sum"),
            pl.col("forward_return").min().alias("return_min"),
            pl.col("forward_return").max().alias("return_max"),
        ).row(0, named=True)
        return {
            "evidence": _without_created_at(output.evidence),
            "frame_summary": summary,
        }, "polars"
    if isinstance(
        output,
        AdaptedFrame | EventWindowResult | PortfolioProjectionResult | SignalTransformResult,
    ):
        source_frame = output.frame
        frame = source_frame.collect() if isinstance(source_frame, pl.LazyFrame) else source_frame
        result = output.evidence
        return {
            "evidence": _without_created_at(result),
            "frame_summary": {
                "rows": frame.height,
                "columns": frame.width,
                "column_names": tuple(frame.columns),
            },
        }, str(result.metadata.parameters.get("backend") or "polars")
    result = (
        output.evidence
        if isinstance(output, SplitResult | CombinatorialSplitResult | PointInTimeJoinResult)
        else output
    )
    parameters = result.metadata.parameters
    backend = parameters.get("backend")
    return _without_created_at(result), str(backend or "polars")


def _checksum(payload: Mapping[str, object]) -> str:
    normalized = _equivalence_value(payload)
    encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _equivalence_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _equivalence_value(item) for key, item in value.items() if key != "backend"
        }
    if isinstance(value, list | tuple):
        return [_equivalence_value(item) for item in value]
    if isinstance(value, float):
        return float(format(value, ".12g"))
    return value


def _measure(
    name: str,
    operation: BenchmarkCallable,
    *,
    work_items: int,
    throughput_unit: str,
    config: BenchmarkConfig,
    trace_sink: list[_BenchmarkTrace] | None = None,
    measure_python_memory: bool = True,
) -> BenchmarkCase:
    baseline_rss_bytes = _current_rss_bytes()
    baseline_peak_rss_bytes = _process_peak_rss_bytes()
    for _ in range(config.warmups):
        operation()
    timings: list[float] = []
    checksums: set[str] = set()
    backend = "unknown"
    for _ in range(config.repetitions):
        gc.collect()
        started = time.perf_counter()
        output = operation()
        elapsed = time.perf_counter() - started
        payload, backend = _output_payload(output)
        timings.append(elapsed)
        checksums.add(_checksum(payload))
    if len(checksums) != 1:
        raise RuntimeError(f"benchmark case {name!r} produced non-deterministic evidence")

    peak_bytes = 0
    if measure_python_memory:
        gc.collect()
        tracemalloc.start()
        memory_output = operation()
        _, peak_bytes = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        memory_payload, memory_backend = _output_payload(memory_output)
        memory_checksum = _checksum(memory_payload)
        if memory_checksum not in checksums or memory_backend != backend:
            raise RuntimeError(f"benchmark case {name!r} changed during memory measurement")

    median_seconds = statistics.median(timings)
    case = BenchmarkCase(
        name=name,
        backend=backend,
        median_seconds=median_seconds,
        minimum_seconds=min(timings),
        maximum_seconds=max(timings),
        throughput=work_items / median_seconds if median_seconds else float(work_items),
        throughput_unit=throughput_unit,
        python_traced_peak_bytes=peak_bytes,
        checksum=checksums.pop(),
    )
    if trace_sink is not None:
        process_peak_rss_bytes = _process_peak_rss_bytes()
        incremental_peak_rss_bytes = None
        if process_peak_rss_bytes is not None:
            baseline = baseline_peak_rss_bytes or baseline_rss_bytes
            if baseline is not None:
                incremental_peak_rss_bytes = max(0, process_peak_rss_bytes - baseline)
        trace_sink.append(
            _BenchmarkTrace(
                name=name,
                timings_seconds=tuple(timings),
                baseline_rss_bytes=baseline_rss_bytes,
                process_peak_rss_bytes=process_peak_rss_bytes,
                incremental_peak_rss_bytes=incremental_peak_rss_bytes,
                python_traced_peak_bytes=peak_bytes,
            )
        )
    return case


def _current_rss_bytes() -> int | None:
    """Return current Linux RSS when available without adding a runtime dependency."""

    if platform.system() != "Linux":
        return None
    try:
        with open("/proc/self/status", encoding="utf-8") as status:
            for line in status:
                if line.startswith("VmRSS:"):
                    fields = line.split()
                    return int(fields[1]) * 1024
    except OSError:  # pragma: no cover - procfs may be unavailable in containers
        return None
    return None


def _process_peak_rss_bytes() -> int | None:
    try:
        import resource
    except ImportError:  # pragma: no cover - Windows
        return None
    peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return peak if platform.system() == "Darwin" else peak * 1024


def _standard_audit_workflow(
    config: BenchmarkConfig,
    observations: pl.DataFrame,
    prices: pl.DataFrame,
    trades: pl.DataFrame,
    decisions: pl.DataFrame,
    available_records: pl.DataFrame,
    interval_frame: pl.DataFrame,
    bootstrap_values: npt.NDArray[np.float64],
    *,
    use_native: bool,
) -> AuditReport:
    """Execute the released cross-phase strategy-audit path as one workload."""

    labels = forward_returns(
        prices,
        horizons=config.horizon_names,
        price_adjustment="raw",
    )
    signal_result = signal.ic(observations, labels, use_native=use_native)
    split_result = PurgedKFold(n_splits=5, embargo=2, use_native=use_native).split(interval_frame)
    bootstrap_result = bootstrap(
        bootstrap_values,
        method="stationary",
        expected_block_length=max(2, round(len(bootstrap_values) ** (1 / 3))),
        resamples=config.bootstrap_resamples,
        seed=config.seed,
        use_native=use_native,
    )
    cost_result = costs.stress(
        trades,
        spread_bps=(0.0, 5.0, 10.0),
        slippage_bps=(0.0, 5.0, 10.0),
    )
    point_in_time = bias.asof_join(
        decisions,
        available_records,
        revision_mode="not_applicable",
    )
    vendor = adapt_vendor(
        available_records,
        VendorSchema(
            schema_id="lacuna.benchmark.vendor.v1",
            columns={
                "available_time": "available_time",
                "instrument": "instrument",
                "value": "value",
            },
            required=("available_time", "instrument", "value"),
            availability="point_in_time",
            revisions="not_applicable",
        ),
        collect=True,
    )
    backtest = adapt_backtest(
        pl.DataFrame(
            {
                "time": np.arange(len(bootstrap_values), dtype=np.int64),
                "strategy": ["benchmark"] * len(bootstrap_values),
                "return": bootstrap_values,
            }
        ),
        BacktestSchema(
            schema_id="lacuna.benchmark.backtest.v1",
            artifact="returns",
            columns={"time": "time", "strategy": "strategy", "return": "return"},
            semantics=BacktestSemantics(
                returns="net",
                return_frequency="daily",
                compounding="simple",
                position_timing="close-to-close",
                execution_delay="one session",
                price_field="close",
                price_adjustment="raw",
                costs="included",
                borrow="included",
                timezone="UTC",
                calendar="synthetic",
                session="regular",
                missing_instruments="retain as null",
                delistings="terminal return included",
            ),
        ),
        collect=True,
    )
    report = standard_audit(
        results={
            "backtest_adapter": backtest.evidence,
            "cost_stress": cost_result,
            "forward_returns": labels.evidence,
            "point_in_time": point_in_time.evidence,
            "purged_split": split_result.evidence,
            "signal_ic": signal_result,
            "stationary_bootstrap": bootstrap_result,
            "vendor_adapter": vendor.evidence,
        },
        scope="strategy",
    )
    if report.metrics["recognized_result_count"] != 8:
        raise RuntimeError("integrated benchmark evidence was not fully recognized")
    return report


def _run_benchmarks(
    config: BenchmarkConfig | None = None,
    *,
    use_native: bool = True,
    case_names: frozenset[str] | None = None,
    trace_sink: list[_BenchmarkTrace] | None = None,
    measure_python_memory: bool = True,
) -> BenchmarkSuite:
    """Measure released public workflows without enforcing machine-specific speed budgets."""

    resolved = config or BenchmarkConfig()
    observations, prices = _panels(resolved)
    trades = _trades(resolved)
    decisions = observations.select(
        pl.col("time").alias("decision_time"),
        "instrument",
    )
    available_records = prices.filter(pl.col("time") % 2 == 0).select(
        pl.col("time").alias("available_time"),
        "instrument",
        pl.col("close").alias("value"),
    )
    labels = forward_returns(
        prices,
        horizons=resolved.horizon_names,
        price_adjustment="raw",
    )
    interval_count = min(resolved.rows, 100_000)
    starts: IntArray = np.arange(interval_count, dtype=np.int64)
    interval_frame = pl.DataFrame(
        {
            "observation_time": starts,
            "label_start": starts,
            "label_end": starts + 1 + starts % max(resolved.horizons),
        }
    )
    bootstrap_values = np.sin(np.arange(max(resolved.periods, 20), dtype=np.float64) * 0.17)
    inference_periods = 6 * math.ceil(max(resolved.periods, 24) / 6)
    inference_strategies = max(3, min(resolved.instruments, 12))
    inference_time: npt.NDArray[np.float64] = np.arange(inference_periods, dtype=np.float64)[
        :, np.newaxis
    ]
    inference_identity: npt.NDArray[np.float64] = np.arange(inference_strategies, dtype=np.float64)[
        np.newaxis, :
    ]
    inference_matrix = (
        np.sin(inference_time * 0.17 + inference_identity * 0.31) + inference_identity * 0.01
    )
    group_count = max(1, min(10, resolved.instruments // resolved.quantiles))
    diagnostic_observations = observations.with_columns(
        (pl.col("instrument") % group_count).cast(pl.String).alias("sector"),
        (pl.col("instrument") / max(resolved.instruments - 1, 1)).alias("market_beta"),
    )
    null_stride = max(resolved.instruments * 7, 1)
    null_heavy_observations = (
        diagnostic_observations.with_row_index("_row")
        .with_columns(
            pl.when(pl.col("_row") % null_stride == 0)
            .then(None)
            .otherwise(pl.col("signal"))
            .alias("signal")
        )
        .drop("_row")
    )
    bucket_spec = signal.BucketSpec.quantiles(count=resolved.quantiles)
    bucketed = signal.bucketize(observations, spec=bucket_spec)
    chunk_size = max(1, observations.height // 3)
    chunked_observations = pl.concat(
        [
            observations.slice(0, chunk_size),
            observations.slice(chunk_size, chunk_size),
            observations.slice(chunk_size * 2),
        ],
        rechunk=False,
    )
    factor_schema = FactorPanelSchema(
        schema_id="benchmark.factor-panel.v1",
        columns={
            "observation_time": "time",
            "instrument": "instrument",
            "signal": "signal",
        },
        semantics=FactorPanelSemantics(
            signal_observation="synthetic observation index",
            decision_time_rule="same synthetic observation",
            forward_return_entry="not_applicable",
            forward_return_exit="not_applicable",
            horizon_clock="trading_observations",
            timezone="UTC",
            calendar="synthetic",
            adjustment_policy="not_applicable",
            group_availability="not_applicable",
            imported_bucket_definition="not_applicable",
        ),
    )
    event_rows: list[dict[str, object]] = []
    event_number = 0
    for instrument in range(min(resolved.instruments, 8)):
        for event_time in range(1, max(2, resolved.periods - 2), 4):
            event_rows.append(
                {
                    "event_id": f"event-{event_number}",
                    "instrument": instrument,
                    "event_time": event_time,
                    "available_time": event_time,
                }
            )
            event_number += 1
    event_frame = pl.DataFrame(event_rows)

    cases: list[tuple[str, BenchmarkCallable, int, str]] = [
        (
            "labels.forward_returns",
            lambda: forward_returns(
                prices,
                horizons=resolved.horizon_names,
                price_adjustment="raw",
            ),
            resolved.rows,
            "input_rows/second",
        ),
        (
            "signal.ic.reference",
            lambda: signal.ic(observations, labels, use_native=False),
            resolved.rows,
            "input_rows/second",
        ),
        (
            "signal.quantiles",
            lambda: signal.quantiles(
                observations,
                labels,
                quantiles=resolved.quantiles,
            ),
            resolved.rows,
            "input_rows/second",
        ),
        (
            "signal.turnover",
            lambda: signal.turnover(observations, quantiles=resolved.quantiles),
            resolved.rows,
            "input_rows/second",
        ),
        (
            "signal.bucketize.grouped_nulls",
            lambda: signal.bucketize(
                null_heavy_observations,
                spec=bucket_spec,
                by=("time", "sector"),
                small_group_policy="drop",
            ),
            resolved.rows,
            "input_rows/second",
        ),
        (
            "signal.neutralize.grouped",
            lambda: signal.neutralize(
                diagnostic_observations,
                exposures=("market_beta", "sector"),
                categorical=("sector",),
                min_residual_df=1,
            ),
            resolved.rows,
            "input_rows/second",
        ),
        (
            "signal.turnover.multi_lag",
            lambda: signal.turnover(
                observations,
                quantiles=resolved.quantiles,
                lags=(1, min(5, resolved.periods - 1)),
            ),
            resolved.rows,
            "input_rows/second",
        ),
        (
            "signal.portfolio_projection",
            lambda: signal.portfolio_projection(
                bucketed,
                labels,
                horizon=resolved.horizon_names[0],
                long_buckets=(resolved.quantiles,),
                short_buckets=(1,),
            ),
            resolved.rows,
            "input_rows/second",
        ),
        (
            "adapters.factor_panel.chunked",
            lambda: adapt_factor_panel(chunked_observations, factor_schema),
            resolved.rows,
            "input_rows/second",
        ),
        (
            "events.event_windows",
            lambda: events.event_windows(
                event_frame,
                prices,
                before=1,
                after=2,
                price_adjustment="raw",
            ),
            len(event_rows) * 4,
            "window_rows/second",
        ),
        (
            "signal.decay.reference",
            lambda: signal.decay(
                observations,
                labels,
                quantile_count=resolved.quantiles,
                use_native=False,
            ),
            resolved.rows,
            "input_rows/second",
        ),
        (
            "validation.bootstrap.reference",
            lambda: bootstrap(
                bootstrap_values,
                method="stationary",
                expected_block_length=max(2, round(len(bootstrap_values) ** (1 / 3))),
                resamples=resolved.bootstrap_resamples,
                seed=resolved.seed,
                use_native=False,
            ),
            resolved.bootstrap_resamples,
            "resamples/second",
        ),
        (
            "cv.purged_kfold.reference",
            lambda: PurgedKFold(n_splits=5, embargo=2, use_native=False).split(interval_frame),
            interval_count,
            "intervals/second",
        ),
        (
            "cv.combinatorial_purged_kfold.reference",
            lambda: CombinatorialPurgedKFold(
                n_groups=6,
                n_test_groups=2,
                embargo=2,
                use_native=False,
            ).split(interval_frame),
            interval_count,
            "intervals/second",
        ),
        (
            "validation.pbo.reference",
            lambda: probability_of_backtest_overfitting(
                inference_matrix,
                partitions=6,
                statistic="mean",
            ),
            math.comb(6, 3),
            "combinations/second",
        ),
        (
            "validation.reality_check.reference",
            lambda: reality_check(
                inference_matrix,
                expected_block_length=3,
                resamples=resolved.bootstrap_resamples,
                seed=resolved.seed,
            ),
            resolved.bootstrap_resamples,
            "resamples/second",
        ),
        (
            "validation.spa.reference",
            lambda: superior_predictive_ability(
                inference_matrix,
                expected_block_length=3,
                resamples=resolved.bootstrap_resamples,
                seed=resolved.seed,
            ),
            resolved.bootstrap_resamples,
            "resamples/second",
        ),
        (
            "study.audit",
            lambda: SignalStudy(
                signal=observations,
                prices=prices,
                horizons=resolved.horizon_names,
                price_adjustment="raw",
                quantiles=resolved.quantiles,
            ).audit(
                bootstrap_resamples=resolved.bootstrap_resamples,
                seed=resolved.seed,
                use_native=use_native,
            ),
            resolved.rows,
            "input_rows/second",
        ),
        (
            "costs.stress.reference",
            lambda: costs.stress(
                trades,
                spread_bps=(0.0, 5.0, 10.0),
                slippage_bps=(0.0, 5.0, 10.0),
            ),
            resolved.rows * 9,
            "scenario_rows/second",
        ),
        (
            "bias.asof_join.reference",
            lambda: bias.asof_join(
                decisions,
                available_records,
                revision_mode="not_applicable",
            ),
            resolved.rows,
            "left_rows/second",
        ),
        (
            "workflow.standard_audit.strategy",
            lambda: _standard_audit_workflow(
                resolved,
                observations,
                prices,
                trades,
                decisions,
                available_records,
                interval_frame,
                bootstrap_values,
                use_native=use_native,
            ),
            resolved.rows,
            "panel_rows/second",
        ),
    ]
    requested_private_cost_cases = (
        set() if case_names is None else case_names.intersection(_PRIVATE_MIGRATION_COST_CASES)
    )
    if requested_private_cost_cases:
        market_trades = trades.with_columns(
            (pl.col("quantity").abs() * 500.0).alias("adv"),
            (
                0.15 + pl.col("instrument").cast(pl.Float64) / max(10.0 * resolved.instruments, 1.0)
            ).alias("volatility"),
            pl.col("execution_time").alias("market_available_time"),
        )
        capacity_capital = tuple(float(1_000_000 * scale) for scale in range(1, 11))
        capacity_scenarios = (
            costs.CapacityScenario("low", impact_coefficient=0.1, spread_bps=1.0),
            costs.CapacityScenario(
                "base", impact_coefficient=0.3, spread_bps=3.0, slippage_bps=1.0
            ),
            costs.CapacityScenario(
                "stress", impact_coefficient=0.7, spread_bps=8.0, slippage_bps=5.0
            ),
        )
        private_cost_cases: dict[str, tuple[BenchmarkCallable, int, str]] = {
            "migration.costs.stress.public": (
                lambda: costs.stress(
                    trades,
                    spread_bps=(0.0, 5.0, 10.0),
                    slippage_bps=(0.0, 5.0, 10.0),
                ),
                resolved.rows * 9,
                "scenario_rows/second",
            ),
            "migration.costs.capacity.public": (
                lambda: costs.capacity_curve(
                    market_trades,
                    capital=capacity_capital,
                    base_capital=1_000_000.0,
                    scenarios=capacity_scenarios,
                    available_time="market_available_time",
                    classification_mode="point_in_time",
                    annualization=252.0,
                ),
                resolved.rows * len(capacity_capital) * len(capacity_scenarios),
                "scenario_rows/second",
            ),
            "migration.costs.break_even.public": (
                lambda: costs.break_even_cost(
                    trades,
                    metric="net_pnl",
                    threshold=0.0,
                    upper_bps=1_000.0,
                    tolerance_bps=1e-6,
                ),
                resolved.rows * 33,
                "solver_rows/second",
            ),
        }
        cases.extend(
            (name, *private_cost_cases[name]) for name in sorted(requested_private_cost_cases)
        )
    requested_private_validation_cases = (
        set()
        if case_names is None
        else case_names.intersection(_PRIVATE_MIGRATION_VALIDATION_CASES)
    )
    if "migration.validation.permutation.public" in requested_private_validation_cases:
        cases.append(
            (
                "migration.validation.permutation.public",
                lambda: permutation_test(
                    inference_matrix[:, :2],
                    paired_with="benchmark",
                    statistic="pearson",
                    scheme="unrestricted",
                    permutations=resolved.bootstrap_resamples * 2,
                    seed=resolved.seed,
                ),
                inference_matrix.shape[0] * resolved.bootstrap_resamples * 2,
                "permuted_rows/second",
            )
        )
    native = native_status()
    if use_native and native.available:
        cases.extend(
            [
                (
                    "signal.ic.native",
                    lambda: signal.ic(observations, labels, use_native=True),
                    resolved.rows,
                    "input_rows/second",
                ),
                (
                    "validation.bootstrap.native",
                    lambda: bootstrap(
                        bootstrap_values,
                        method="stationary",
                        expected_block_length=max(2, round(len(bootstrap_values) ** (1 / 3))),
                        resamples=resolved.bootstrap_resamples,
                        seed=resolved.seed,
                        use_native=True,
                    ),
                    resolved.bootstrap_resamples,
                    "resamples/second",
                ),
                (
                    "cv.purged_kfold.native",
                    lambda: PurgedKFold(n_splits=5, embargo=2, use_native=True).split(
                        interval_frame
                    ),
                    interval_count,
                    "intervals/second",
                ),
            ]
        )
    if case_names is not None:
        available_names = {name for name, _, _, _ in cases}
        missing_names = sorted(case_names - available_names)
        if missing_names:
            raise MethodContractError(
                f"benchmark cases are unavailable under this backend: {missing_names}"
            )
        cases = [case for case in cases if case[0] in case_names]
    measurements = tuple(
        _measure(
            name,
            operation,
            work_items=work_items,
            throughput_unit=unit,
            config=resolved,
            trace_sink=trace_sink,
            measure_python_memory=measure_python_memory,
        )
        for name, operation, work_items, unit in cases
    )
    return BenchmarkSuite(
        config=resolved,
        cases=measurements,
        generated_at=datetime.now(UTC),
        environment={
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor() or None,
            "polars": pl.__version__,
            "numpy": np.__version__,
            "native_available": native.available,
            "native_version": native.version,
            "process_peak_rss_bytes": _process_peak_rss_bytes(),
            "memory_measurement": "tracemalloc peak; native allocations may not be attributed",
            "timing_clock": "time.perf_counter",
            "checksum_normalization": (
                "backend excluded; finite floats rounded to 12 significant digits"
            ),
        },
    )


def _run_benchmark_case_detailed(
    name: str,
    config: BenchmarkConfig,
    *,
    use_native: bool,
    measure_python_memory: bool = True,
) -> tuple[BenchmarkCase, _BenchmarkTrace, Mapping[str, object]]:
    """Measure one prepared public case for an isolated migration worker."""

    traces: list[_BenchmarkTrace] = []
    suite = _run_benchmarks(
        config,
        use_native=use_native,
        case_names=frozenset({name}),
        trace_sink=traces,
        measure_python_memory=measure_python_memory,
    )
    if len(suite.cases) != 1 or len(traces) != 1:
        raise RuntimeError(f"isolated benchmark case {name!r} did not produce one measurement")
    return suite.cases[0], traces[0], suite.environment


def run_benchmarks(
    config: BenchmarkConfig | None = None,
    *,
    use_native: bool = True,
) -> BenchmarkSuite:
    """Measure released public workflows without enforcing machine-specific speed budgets."""

    return _run_benchmarks(config, use_native=use_native)


__all__ = [
    "BenchmarkCase",
    "BenchmarkConfig",
    "BenchmarkSuite",
    "benchmark_config_for_tier",
    "run_benchmarks",
]
