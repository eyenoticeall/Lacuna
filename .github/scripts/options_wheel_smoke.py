"""Exercise installed core and lacuna-options wheels without development dependencies."""

from __future__ import annotations

import json
import math
from datetime import date, timedelta
from importlib import metadata
from importlib.resources import files

import lacuna_options

import lacuna


def require(condition: bool, message: str) -> None:
    """Fail the artifact smoke check with a useful contract message."""

    if not condition:
        raise RuntimeError(message)


start = date(2026, 1, 1)
chain = lacuna_options.validate_chain(
    {
        "time": [start, start],
        "instrument": ["A-C", "A-P"],
        "underlying": ["A", "A"],
        "expiration": [start + timedelta(days=30), start + timedelta(days=30)],
        "strike": [100.0, 95.0],
        "option_type": ["call", "put"],
        "bid": [2.0, 1.0],
        "ask": [4.0, 3.0],
        "underlying_price": [98.0, 98.0],
        "rate": [0.03, 0.03],
        "dividend": [0.01, 0.01],
        "iv": [0.24, 0.30],
        "delta": [0.45, -0.25],
        "fair_iv": [0.20, 0.32],
    }
)
bucketed = lacuna_options.delta_buckets(chain)
residual = lacuna_options.empirical_residual(chain, expected="fair_iv")

distribution_version = metadata.version("lacuna-options")
require(
    lacuna_options.__version__ == distribution_version,
    "lacuna-options package and distribution versions disagree",
)
require(chain.evidence.metrics["quote_count"] == 2, "option-chain validation failed")
require("delta_bucket" in bucketed.frame.columns, "delta bucketing failed")
residual_values = residual.frame.get_column("iv_residual").to_list()
require(len(residual_values) == 2, "empirical residual row count failed")
require(math.isclose(residual_values[0], 0.04, abs_tol=1e-14), "positive residual failed")
require(math.isclose(residual_values[1], -0.02, abs_tol=1e-14), "negative residual failed")
require(files("lacuna_options").joinpath("py.typed").is_file(), "options wheel is not typed")

print(
    json.dumps(
        {
            "lacuna_version": lacuna.__version__,
            "options_version": distribution_version,
            "quotes": chain.evidence.metrics["quote_count"],
            "occupied_delta_buckets": bucketed.evidence.metrics["occupied_buckets"],
            "mean_iv_residual": residual.evidence.metrics["mean_residual"],
        },
        indent=2,
        sort_keys=True,
    )
)
