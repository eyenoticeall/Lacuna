from __future__ import annotations

import polars as pl
from hypothesis import given
from hypothesis import strategies as st

from lacuna.bias import asof_join, membership_at


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


@given(
    boundaries=st.lists(
        st.integers(min_value=-1_000, max_value=1_000),
        min_size=2,
        max_size=25,
        unique=True,
    ),
    as_of=st.integers(min_value=-1_100, max_value=1_100),
)
def test_membership_intervals_are_half_open_and_order_invariant(
    boundaries: list[int],
    as_of: int,
) -> None:
    ordered = sorted(boundaries)
    valid_to = [*ordered[1:], None]
    frame = pl.DataFrame(
        {
            "index": ["LAC"] * len(ordered),
            "instrument": ["A"] * len(ordered),
            "valid_from": ordered,
            "valid_to": pl.Series(valid_to, dtype=pl.Int64),
            "available_time": ordered,
            "generation": list(range(len(ordered))),
        }
    )

    forward = membership_at(frame, as_of=as_of, source_status="confirmed_safe")
    reverse = membership_at(frame.reverse(), as_of=as_of, source_status="confirmed_safe")
    expected = max(
        (index for index, start in enumerate(ordered) if start <= as_of),
        default=None,
    )

    assert forward.frame.equals(reverse.frame)
    assert forward.evidence.metrics == reverse.evidence.metrics
    if expected is None:
        assert forward.frame.is_empty()
    else:
        assert forward.frame.item(0, "generation") == expected
