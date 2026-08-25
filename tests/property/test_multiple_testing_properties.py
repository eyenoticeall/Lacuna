from __future__ import annotations

from typing import cast

import polars as pl
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from lacuna.validation import multiple_testing

P_VALUES = st.lists(
    st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    min_size=1,
    max_size=25,
)


@pytest.mark.parametrize(
    "method",
    ["bonferroni", "holm", "benjamini_hochberg", "benjamini_yekutieli"],
)
@settings(max_examples=40, deadline=None)
@given(p_values=P_VALUES)
def test_adjusted_p_values_are_bounded_conservative_and_rank_monotone(
    method: str, p_values: list[float]
) -> None:
    result = multiple_testing(p_values, method=method)  # type: ignore[arg-type]
    table = cast(list[dict[str, object]], result.table("adjusted_p_values"))
    ordered = sorted(table, key=lambda row: float(cast(float, row["p_value"])))
    adjusted = [float(cast(float, row["adjusted_p_value"])) for row in ordered]

    assert all(0.0 <= value <= 1.0 for value in adjusted)
    assert adjusted == sorted(adjusted)
    assert all(
        float(cast(float, row["adjusted_p_value"])) + 1e-15 >= float(cast(float, row["p_value"]))
        for row in table
    )


@settings(max_examples=40, deadline=None)
@given(p_values=P_VALUES)
def test_multiple_testing_is_invariant_to_trial_row_order(p_values: list[float]) -> None:
    trial_ids = [f"trial-{index}" for index in range(len(p_values))]
    forward = pl.DataFrame({"trial_id": trial_ids, "p_value": p_values})
    reverse = forward.reverse()

    first = multiple_testing(forward, method="benjamini_yekutieli")
    second = multiple_testing(reverse, method="benjamini_yekutieli")
    first_values = {
        str(row["trial_id"]): float(cast(float, row["adjusted_p_value"]))
        for row in cast(list[dict[str, object]], first.table("adjusted_p_values"))
    }
    second_values = {
        str(row["trial_id"]): float(cast(float, row["adjusted_p_value"]))
        for row in cast(list[dict[str, object]], second.table("adjusted_p_values"))
    }

    assert first_values == pytest.approx(second_values)
