from __future__ import annotations

import polars as pl
from hypothesis import given
from hypothesis import strategies as st

from lacuna.signal import quantiles


@st.composite
def _quantile_case(draw: st.DrawFn) -> tuple[list[int], list[float], int]:
    count = draw(st.integers(min_value=2, max_value=40))
    quantile_count = draw(st.integers(min_value=2, max_value=min(10, count)))
    signals = draw(st.lists(st.integers(-5, 5), min_size=count, max_size=count))
    returns = draw(
        st.lists(
            st.floats(
                min_value=-10,
                max_value=10,
                allow_nan=False,
                allow_infinity=False,
            ),
            min_size=count,
            max_size=count,
        )
    )
    return signals, returns, quantile_count


@given(_quantile_case())
def test_balanced_quantiles_conserve_rows_and_differ_by_at_most_one(
    case: tuple[list[int], list[float], int],
) -> None:
    signals, returns, quantile_count = case
    instruments = list(range(len(signals)))
    signal = pl.DataFrame(
        {"time": [0] * len(signals), "instrument": instruments, "signal": signals}
    )
    labels = pl.DataFrame(
        {
            "observation_time": [0] * len(signals),
            "instrument": instruments,
            "forward_return": returns,
        }
    )

    result = quantiles(signal, labels, quantiles=quantile_count)
    rows = result.table("quantile_returns_by_period")
    counts = [row["n_observations"] for row in rows]  # type: ignore[union-attr]
    assert sum(counts) == len(signals)
    assert max(counts) - min(counts) <= 1
