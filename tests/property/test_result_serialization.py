from __future__ import annotations

import json

from hypothesis import given
from hypothesis import strategies as st

from lacuna import AnalysisResult, ResultMetadata


@given(st.dictionaries(st.text(min_size=1), st.integers(), max_size=20))
def test_integer_metrics_round_trip(metrics: dict[str, int]) -> None:
    result = AnalysisResult(metadata=ResultMetadata(method="property.round_trip"), metrics=metrics)
    assert json.loads(result.to_json())["metrics"] == metrics
