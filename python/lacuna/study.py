"""High-level signal-study workflow delegating to functional APIs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal

from lacuna import signal as signal_api
from lacuna.adapters.polars import PolarsFrame, to_polars
from lacuna.audit import AuditContext, AuditRule, run_audit
from lacuna.cv import SplitResult
from lacuna.exceptions import MethodContractError
from lacuna.labels import Horizon, LabelResult, PriceAdjustment, forward_returns
from lacuna.report import AuditReport
from lacuna.types import AnalysisResult, JsonValue
from lacuna.validation import bootstrap


def _owned_frame(data: object, schema: Sequence[str] | None) -> PolarsFrame:
    normalized = to_polars(data, schema=schema)
    return normalized.clone()


class SignalStudy:
    """Reusable v0.1 workflow for a cross-sectional signal and price panel."""

    __slots__ = (
        "_allow_same_close",
        "_delisting_return",
        "_entry",
        "_exit",
        "_horizons",
        "_instrument",
        "_label_missing",
        "_label_result",
        "_price",
        "_price_adjustment",
        "_price_time",
        "_prices",
        "_quantile_count",
        "_signal",
        "_signal_observed_at",
        "_signal_time",
        "_signal_value",
    )

    def __init__(
        self,
        *,
        signal: object,
        prices: object,
        horizons: Sequence[Horizon] = ("1D", "5D", "20D"),
        signal_schema: Sequence[str] | None = None,
        price_schema: Sequence[str] | None = None,
        signal_time: str = "time",
        price_time: str = "time",
        instrument: str = "instrument",
        signal_value: str = "signal",
        price: str = "close",
        entry: str | None = None,
        exit: str = "close",
        signal_observed_at: Literal["open", "close"] | None = None,
        price_adjustment: PriceAdjustment = "unknown",
        delisting_return: str | None = None,
        missing: Literal["drop", "raise"] = "drop",
        allow_same_close: bool = False,
        quantiles: int = 5,
    ) -> None:
        self._signal = _owned_frame(signal, signal_schema)
        self._prices = _owned_frame(prices, price_schema)
        self._horizons = tuple(horizons)
        self._signal_time = signal_time
        self._price_time = price_time
        self._instrument = instrument
        self._signal_value = signal_value
        self._price = price
        self._entry = entry
        self._exit = exit
        self._signal_observed_at = signal_observed_at
        self._price_adjustment = price_adjustment
        self._delisting_return = delisting_return
        self._label_missing = missing
        self._allow_same_close = allow_same_close
        self._quantile_count = quantiles
        self._label_result: LabelResult | None = None

    def labels(self) -> LabelResult:
        """Construct and cache explicit forward labels."""

        if self._label_result is None:
            self._label_result = forward_returns(
                self._prices,
                horizons=self._horizons,
                time=self._price_time,
                instrument=self._instrument,
                price=self._price,
                signal_time=self._signal_observed_at,
                entry=self._entry,
                exit=self._exit,
                price_adjustment=self._price_adjustment,
                delisting_return=self._delisting_return,
                missing=self._label_missing,
                allow_same_close=self._allow_same_close,
            )
        return self._label_result

    def ic(
        self,
        *,
        method: Literal["pearson", "spearman"] = "spearman",
        min_observations: int = 3,
        use_native: bool = True,
    ) -> AnalysisResult:
        """Delegate to the functional IC implementation."""

        return signal_api.ic(
            self._signal,
            self.labels(),
            method=method,
            signal_time=self._signal_time,
            instrument=self._instrument,
            signal_value=self._signal_value,
            min_observations=min_observations,
            use_native=use_native,
        )

    def quantiles(self, *, quantiles: int | None = None) -> AnalysisResult:
        """Delegate to deterministic quantile-return analysis."""

        return signal_api.quantiles(
            self._signal,
            self.labels(),
            quantiles=self._quantile_count if quantiles is None else quantiles,
            signal_time=self._signal_time,
            instrument=self._instrument,
            signal_value=self._signal_value,
        )

    def turnover(self, *, quantiles: int | None = None) -> AnalysisResult:
        """Measure consecutive-period signal turnover."""

        return signal_api.turnover(
            self._signal,
            time=self._signal_time,
            instrument=self._instrument,
            signal_value=self._signal_value,
            quantiles=self._quantile_count if quantiles is None else quantiles,
        )

    def decay(
        self,
        *,
        min_observations: int = 3,
        quantiles: int | None = None,
        use_native: bool = True,
    ) -> AnalysisResult:
        """Evaluate IC and spread across the study horizons."""

        return signal_api.decay(
            self._signal,
            self.labels(),
            signal_time=self._signal_time,
            instrument=self._instrument,
            signal_value=self._signal_value,
            min_observations=min_observations,
            quantile_count=self._quantile_count if quantiles is None else quantiles,
            use_native=use_native,
        )

    def audit(
        self,
        *,
        bootstrap_resamples: int = 1_000,
        seed: int | None = None,
        min_observations: int = 3,
        split: SplitResult | AnalysisResult | None = None,
        policies: Mapping[str, JsonValue] | None = None,
        rules: Sequence[AuditRule] | None = None,
        use_native: bool = True,
    ) -> AuditReport:
        """Compute the v0.1 diagnostics and renderable structured audit."""

        if bootstrap_resamples < 100:
            raise MethodContractError("bootstrap_resamples must be at least 100")
        if seed is not None and seed < 0:
            raise MethodContractError("seed must be non-negative")

        labels = self.labels()
        ic_result = self.ic(min_observations=min_observations, use_native=use_native)
        quantile_result = self.quantiles()
        turnover_result = self.turnover()
        decay_result = self.decay(
            min_observations=min_observations,
            use_native=use_native,
        )
        results: dict[str, AnalysisResult] = {
            "labels": labels.evidence,
            "ic": ic_result,
            "quantiles": quantile_result,
            "turnover": turnover_result,
            "decay": decay_result,
        }
        ic_table = ic_result.table("ic_by_period")
        if isinstance(ic_table, list):
            ic_values = [
                row["ic"]
                for row in ic_table
                if isinstance(row, Mapping) and isinstance(row.get("ic"), int | float)
            ]
            if len(ic_values) >= 2:
                block_length = max(2, min(len(ic_values), round(len(ic_values) ** (1 / 3))))
                results["bootstrap"] = bootstrap(
                    ic_values,
                    method="stationary",
                    expected_block_length=block_length,
                    resamples=bootstrap_resamples,
                    seed=seed,
                    use_native=use_native,
                )
        if split is not None:
            results["split"] = split.evidence if isinstance(split, SplitResult) else split
        effective_policies: dict[str, JsonValue] = {"study_type": "signal"}
        if policies is not None:
            effective_policies.update(policies)
        result = run_audit(
            AuditContext(results=results, policies=effective_policies),
            rules=rules,
        )
        return AuditReport(result)


__all__ = ["SignalStudy"]
