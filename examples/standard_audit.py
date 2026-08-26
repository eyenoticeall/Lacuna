"""Compose vendor and backtester provenance into a standardized strategy audit."""

from __future__ import annotations

from datetime import UTC, datetime

import polars as pl

import lacuna as lc


def build_standard_audit() -> tuple[lc.AuditReport, dict[str, lc.AnalysisResult]]:
    """Return a report whose missing cross-phase evidence remains explicitly UNKNOWN."""

    vendor_frame = pl.DataFrame(
        {
            "asset_id": ["A", "B"],
            "published_at": [
                datetime(2026, 1, 2, 13, tzinfo=UTC),
                datetime(2026, 1, 2, 13, tzinfo=UTC),
            ],
            "close_px": [101.0, 49.5],
        }
    )
    vendor = lc.adapters.adapt_vendor(
        vendor_frame,
        lc.adapters.VendorSchema(
            "example.vendor.prices.v1",
            {
                "instrument": "asset_id",
                "available_time": "published_at",
                "close": "close_px",
            },
            required=("instrument", "available_time", "close"),
            availability="point_in_time",
            revisions="not_applicable",
            timezone="UTC",
            timezone_columns=("available_time",),
            price_adjustment="total_return_adjusted",
            identifier_policy="permanent_asset_id",
        ),
        collect=False,
    )
    backtest = lc.adapters.adapt_backtest(
        {
            "date": [1, 2],
            "model": ["alpha", "alpha"],
            "net_return": [0.01, -0.004],
        },
        lc.adapters.BacktestSchema(
            "example.backtest.returns.v1",
            "returns",
            {"time": "date", "strategy": "model", "return": "net_return"},
            lc.adapters.BacktestSemantics(
                returns="net",
                return_frequency="daily",
                compounding="simple",
                position_timing="previous close",
                execution_delay="one session",
                price_field="close",
                price_adjustment="total_return_adjusted",
                costs="included",
                borrow="included",
                timezone="UTC",
                calendar="XNYS",
                session="regular",
                missing_instruments="retain as null",
                delistings="terminal return included",
            ),
        ),
        collect=True,
    )
    evidence = {
        "vendor_prices": vendor.evidence,
        "backtest_returns": backtest.evidence,
    }
    return lc.standard_audit(results=evidence, scope="strategy"), evidence


report, evidence = build_standard_audit()
print(report.to_json())

# Persist the same review plus its named evidence when an artifact is wanted:
# report.bundle("strategy-audit.lacuna", evidence=evidence)
