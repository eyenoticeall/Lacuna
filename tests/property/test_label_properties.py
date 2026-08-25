from __future__ import annotations

import polars as pl
import pytest
from hypothesis import given
from hypothesis import strategies as st

from lacuna.labels import forward_returns


@given(
    st.lists(
        st.floats(
            min_value=0.01,
            max_value=1_000_000,
            allow_nan=False,
            allow_infinity=False,
        ),
        min_size=3,
        max_size=30,
    ),
    st.floats(
        min_value=0.01,
        max_value=1_000,
        allow_nan=False,
        allow_infinity=False,
    ),
)
def test_forward_returns_are_invariant_to_positive_price_scale(
    prices: list[float], scale: float
) -> None:
    frame = pl.DataFrame(
        {"time": range(len(prices)), "instrument": ["A"] * len(prices), "close": prices}
    )
    baseline = forward_returns(frame, horizon="1D", price_adjustment="raw").frame
    scaled = forward_returns(
        frame.with_columns((pl.col("close") * scale).alias("close")),
        horizon="1D",
        price_adjustment="raw",
    ).frame

    assert scaled.get_column("forward_return").to_list() == pytest.approx(
        baseline.get_column("forward_return").to_list(), rel=1e-12, abs=1e-12
    )
    assert baseline.select("label_start", "entry_time", "label_end").equals(
        scaled.select("label_start", "entry_time", "label_end")
    )
