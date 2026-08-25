from __future__ import annotations

import math
from datetime import date, timedelta

import polars as pl
import pytest
from hypothesis import given
from hypothesis import strategies as st

from lacuna_options import empirical_residual, validate_chain


@given(
    spot=st.floats(min_value=1.0, max_value=10_000.0, allow_nan=False, allow_infinity=False),
    strike=st.floats(min_value=1.0, max_value=10_000.0, allow_nan=False, allow_infinity=False),
    rate=st.floats(min_value=-0.1, max_value=0.25, allow_nan=False, allow_infinity=False),
    dividend=st.floats(min_value=-0.05, max_value=0.2, allow_nan=False, allow_infinity=False),
    days=st.integers(min_value=1, max_value=3650),
)
def test_forward_and_log_moneyness_match_the_declared_equations(
    spot: float,
    strike: float,
    rate: float,
    dividend: float,
    days: int,
) -> None:
    start = date(2026, 1, 1)
    frame = pl.DataFrame(
        {
            "time": [start],
            "instrument": ["contract"],
            "underlying": ["asset"],
            "expiration": [start + timedelta(days=days)],
            "strike": [strike],
            "option_type": ["call"],
            "bid": [1.0],
            "ask": [2.0],
            "underlying_price": [spot],
            "rate": [rate],
            "dividend": [dividend],
        }
    )

    chain = validate_chain(frame)
    expected_forward = spot * math.exp((rate - dividend) * days / 365.25)

    assert chain.frame.item(0, "forward") == pytest.approx(expected_forward)
    assert chain.frame.item(0, "log_moneyness") == pytest.approx(
        math.log(strike / expected_forward)
    )


@given(
    observed=st.floats(min_value=0.01, max_value=5.0, allow_nan=False, allow_infinity=False),
    expected=st.floats(min_value=0.01, max_value=5.0, allow_nan=False, allow_infinity=False),
)
def test_empirical_residual_is_exactly_observed_minus_expected(
    observed: float,
    expected: float,
) -> None:
    start = date(2026, 1, 1)
    chain = validate_chain(
        {
            "time": [start],
            "instrument": ["contract"],
            "underlying": ["asset"],
            "expiration": [start + timedelta(days=30)],
            "strike": [100.0],
            "option_type": ["call"],
            "bid": [1.0],
            "ask": [2.0],
            "underlying_price": [100.0],
            "rate": [0.0],
            "dividend": [0.0],
            "iv": [observed],
            "fair_iv": [expected],
        }
    )

    result = empirical_residual(chain, expected="fair_iv")
    assert result.frame.item(0, "iv_residual") == pytest.approx(observed - expected)
