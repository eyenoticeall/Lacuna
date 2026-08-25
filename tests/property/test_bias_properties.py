from __future__ import annotations

import polars as pl
from hypothesis import given
from hypothesis import strategies as st

from lacuna.bias import asof_join


@given(
    decisions=st.lists(
        st.integers(min_value=-1_000, max_value=1_000),
        min_size=1,
        max_size=30,
    ),
    availability=st.lists(
        st.integers(min_value=-1_000, max_value=1_000),
        min_size=1,
        max_size=30,
        unique=True,
    ),
)
def test_asof_join_always_selects_the_latest_nonfuture_record(
    decisions: list[int],
    availability: list[int],
) -> None:
    left = pl.DataFrame(
        {
            "decision_time": decisions,
            "instrument": ["A"] * len(decisions),
            "left_row": list(range(len(decisions))),
        }
    )
    right = pl.DataFrame(
        {
            "available_time": availability,
            "instrument": ["A"] * len(availability),
            "source_time": availability,
        }
    ).reverse()

    result = asof_join(left, right, revision_mode="not_applicable")
    observed = result.frame.get_column("available_time").to_list()
    expected = [
        max((value for value in availability if value <= decision), default=None)
        for decision in decisions
    ]

    assert observed == expected
    assert result.frame.get_column("left_row").to_list() == list(range(len(decisions)))
    assert all(
        matched is None or matched <= decision
        for decision, matched in zip(decisions, observed, strict=True)
    )
    assert result.evidence.metrics["future_matches"] == 0


@given(
    decisions=st.lists(
        st.integers(min_value=0, max_value=1_000),
        min_size=1,
        max_size=20,
    ),
    availability=st.lists(
        st.integers(min_value=0, max_value=1_000),
        min_size=1,
        max_size=20,
        unique=True,
    ),
)
def test_asof_result_is_invariant_to_right_input_order(
    decisions: list[int],
    availability: list[int],
) -> None:
    left = pl.DataFrame({"decision_time": decisions, "instrument": ["A"] * len(decisions)})
    right = pl.DataFrame(
        {
            "available_time": availability,
            "instrument": ["A"] * len(availability),
            "value": [value * 10 for value in availability],
        }
    )

    forward = asof_join(left, right, revision_mode="not_applicable")
    reverse = asof_join(left, right.reverse(), revision_mode="not_applicable")

    assert forward.frame.equals(reverse.frame)
    assert forward.evidence.metrics == reverse.evidence.metrics
