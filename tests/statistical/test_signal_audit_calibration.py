from __future__ import annotations

import numpy as np
import polars as pl

from lacuna.study import SignalStudy
from lacuna.types import FindingState


def _null_study(generator: np.random.Generator, periods: int, instruments: int) -> SignalStudy:
    # A persistent signal with no predictive power: overlapping multi-period labels make
    # adjacent IC values strongly dependent even though every true IC is zero.
    persistence = 0.95
    signal_values = np.empty((periods, instruments))
    signal_values[0] = generator.normal(size=instruments)
    for period in range(1, periods):
        signal_values[period] = persistence * signal_values[period - 1] + np.sqrt(
            1.0 - persistence**2
        ) * generator.normal(size=instruments)
    price_periods = periods + 25
    prices = 100.0 * np.exp(
        np.cumsum(0.01 * generator.normal(size=(price_periods, instruments)), axis=0)
    )
    names = [f"asset-{index}" for index in range(instruments)]
    return SignalStudy(
        signal=pl.DataFrame(
            {
                "time": np.repeat(np.arange(periods), instruments),
                "instrument": np.tile(names, periods),
                "signal": signal_values.ravel(),
            }
        ),
        prices=pl.DataFrame(
            {
                "time": np.repeat(np.arange(price_periods), instruments),
                "instrument": np.tile(names, price_periods),
                "close": prices.ravel(),
            }
        ),
        horizons=("5D", "20D"),
        signal_observed_at="open",
        entry="current_close",
        price_adjustment="total_return_adjusted",
        quantiles=3,
    )


def test_signal_audit_bootstrap_holds_null_size_for_overlapping_labels() -> None:
    # Regression: the audit pooled every (date, horizon) IC and resampled overlapping
    # labels with short blocks, so an uninformative persistent signal excluded zero in
    # roughly a quarter of null runs and often earned BOOTSTRAP_INTERVAL PASS.
    simulations = 40
    excluded = 0
    passed = 0
    for simulation in range(simulations):
        generator = np.random.default_rng(20260928 + simulation)
        report = _null_study(generator, periods=200, instruments=20).audit(
            bootstrap_resamples=200,
            seed=simulation,
            use_native=False,
        )
        interval = report.evidence["bootstrap"].metrics
        lower = float(interval["confidence_lower"])  # type: ignore[arg-type]
        upper = float(interval["confidence_upper"])  # type: ignore[arg-type]
        excluded += int(lower > 0.0 or upper < 0.0)
        states = {finding.code: finding.state for finding in report.findings}
        passed += int(states["BOOTSTRAP_INTERVAL"] == FindingState.PASS)

    # A deterministic guard, not an exact finite-sample claim: nominal two-sided size
    # is 5% (two of forty runs) and one-sided PASS size is 2.5%.
    assert excluded <= 5
    assert passed <= 3
