"""Exercise one affected optional extra from an installed wheel."""

from __future__ import annotations

import argparse
import math

import lacuna


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def statistics_smoke() -> None:
    import scipy

    rows = tuple(
        {
            "observation_time": period,
            "horizon": f"{horizon}D",
            "ic": 0.1 * math.exp(-horizon / 4.0) * (1.0 + 0.01 * math.sin(period)),
        }
        for period in range(20)
        for horizon in (1, 2, 4, 8)
    )
    source = lacuna.AnalysisResult(
        metadata=lacuna.ResultMetadata(method="signal.decay"),
        metrics={"n_horizons": 4},
        tables={"ic_by_period_horizon": rows},
    )
    result = lacuna.signal.fit_decay(source, resamples=100, seed=7)
    require(result.metrics["half_life"] is not None, "statistics extra decay fit failed")
    require(bool(scipy.__version__), "SciPy version is unavailable")


def report_smoke() -> None:
    report = lacuna.AuditReport(
        lacuna.AnalysisResult(
            metadata=lacuna.ResultMetadata(method="audit.extra_smoke"),
            metrics={"evidence_coverage": 1.0},
        )
    )
    rendered = report.to_html(renderer="plotly")
    require("lacuna-panel-01" in rendered, "report extra did not render Plotly evidence")
    require('<script src="http' not in rendered, "report extra requested a remote script")


def pandas_smoke() -> None:
    import pandas as pd

    source = pd.DataFrame(
        {"factor": [0.1, 0.2]},
        index=pd.MultiIndex.from_tuples([(1, "A"), (1, "B")], names=["date", "asset"]),
    )
    semantics = lacuna.adapters.FactorPanelSemantics(
        signal_observation="synthetic",
        decision_time_rule="synthetic",
        forward_return_entry="not_applicable",
        forward_return_exit="not_applicable",
        horizon_clock="trading_observations",
        timezone="UTC",
        calendar="synthetic",
        adjustment_policy="not_applicable",
        group_availability="not_applicable",
        imported_bucket_definition="not_applicable",
    )
    result = lacuna.adapters.adapt_factor_panel(
        source,
        lacuna.adapters.FactorPanelSchema(
            "wheel-smoke.pandas-factor-panel.v1",
            {"observation_time": "date", "instrument": "asset", "signal": "factor"},
            semantics,
        ),
    )
    require(result.evidence.metrics["row_count"] == 2, "pandas factor-panel row count failed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("extra", choices=("statistics", "report", "pandas"))
    extra = parser.parse_args().extra
    {"statistics": statistics_smoke, "report": report_smoke, "pandas": pandas_smoke}[extra]()


if __name__ == "__main__":
    main()
