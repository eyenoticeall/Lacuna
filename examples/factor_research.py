"""Run the complete v0.1 signal-to-audit workflow on deterministic synthetic data."""

from __future__ import annotations

import numpy as np
import polars as pl

import lacuna as lc

periods = 28
instruments = 6
names = [f"asset-{index}" for index in range(instruments)]

prices = pl.DataFrame(
    {
        "time": np.tile(np.arange(periods), instruments),
        "instrument": np.repeat(names, periods),
        "close": [
            100.0 * (1.0 + 0.002 * (instrument + 1)) ** time
            for instrument in range(instruments)
            for time in range(periods)
        ],
        "delisting_return": np.zeros(periods * instruments),
    }
)
signal_periods = periods - 3
factor = pl.DataFrame(
    {
        "time": np.repeat(np.arange(signal_periods), instruments),
        "instrument": np.tile(names, signal_periods),
        "signal": np.tile(np.arange(instruments, dtype=np.float64), signal_periods),
    }
)

study = lc.SignalStudy(
    signal=factor,
    prices=prices,
    horizons=("1D", "2D", "3D"),
    signal_observed_at="open",
    entry="current_close",
    price_adjustment="raw",
    delisting_return="delisting_return",
    quantiles=3,
)
split = lc.cv.PurgedKFold(n_splits=3).split(study.labels().frame)
report = study.audit(
    bootstrap_resamples=100,
    seed=42,
    split=split,
    policies={"survivorship_safe": True, "trial_history_available": True},
)

print(report.to_json())
