"""Run the copy-pasteable getting-started signal audit on synthetic data."""

from __future__ import annotations

from datetime import date, timedelta

import polars as pl

import lacuna as lc

instruments = ("A", "B", "C", "D", "E", "F")
calendar_days = tuple(date(2025, 1, 2) + timedelta(days=offset) for offset in range(50))
sessions = tuple(day for day in calendar_days if day.weekday() < 5)[:35]

prices = pl.DataFrame(
    {
        "time": [session for instrument in instruments for session in sessions],
        "instrument": [instrument for instrument in instruments for _ in sessions],
        "close": [
            100.0 + 4.0 * asset + day * (0.3 + 0.05 * asset) + 0.2 * ((day + asset) % 3)
            for asset, _instrument in enumerate(instruments)
            for day, _session in enumerate(sessions)
        ],
    }
)
signal = pl.DataFrame(
    {
        "time": [session for session in sessions for _ in instruments],
        "instrument": [instrument for _session in sessions for instrument in instruments],
        "signal": [
            float(((day + 2 * asset) % 11) - 5)
            for day, _session in enumerate(sessions)
            for asset, _instrument in enumerate(instruments)
        ],
    }
)

study = lc.SignalStudy(
    signal=signal,
    prices=prices,
    horizons=("1D", "5D", "20D"),
    signal_observed_at="open",
    entry="current_close",
    price_adjustment="total_return_adjusted",
    quantiles=5,
)

ic_result = study.ic()
quantile_result = study.quantiles()
report = study.audit(bootstrap_resamples=200, seed=42)

print(ic_result.table("ic_by_horizon"))
print(quantile_result.table("quantile_returns"))
print(report.summary())
report.to_html("lacuna-audit.html")
print("Wrote lacuna-audit.html")
