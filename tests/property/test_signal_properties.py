from __future__ import annotations

import numpy as np
from hypothesis import given
from hypothesis import strategies as st

from lacuna.signal import ic

SIGNAL_VALUE = st.integers(min_value=-1_000, max_value=1_000)
LABEL_VALUE = st.floats(
    min_value=-1_000,
    max_value=1_000,
    allow_nan=False,
    allow_infinity=False,
)


@given(
    st.lists(
        st.tuples(SIGNAL_VALUE, LABEL_VALUE),
        min_size=3,
        max_size=30,
        unique_by=lambda row: row[0],
    )
)
def test_spearman_is_invariant_to_strictly_increasing_transform(
    rows: list[tuple[int, float]],
) -> None:
    signal = np.asarray([row[0] for row in rows], dtype=np.float64)
    labels = np.asarray([row[1] for row in rows], dtype=np.float64)
    baseline = ic(signal, labels, method="spearman", use_native=False).metrics["mean_ic"]
    transformed = ic(
        signal * 3.0 + 7.0,
        labels,
        method="spearman",
        use_native=False,
    ).metrics["mean_ic"]
    assert baseline == transformed
