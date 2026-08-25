from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from lacuna.adapters import frame_summary, require_columns, to_polars
from lacuna.exceptions import DataContractError


def test_polars_lazy_frame_stays_lazy() -> None:
    source = pl.DataFrame({"time": [1], "instrument": ["A"], "signal": [0.2]}).lazy()
    normalized = to_polars(source)

    assert isinstance(normalized, pl.LazyFrame)
    assert frame_summary(normalized).lazy is True
    assert require_columns(normalized, ["time", "instrument", "signal"]) is normalized


def test_polars_series_becomes_a_single_column_frame() -> None:
    normalized = to_polars(pl.Series("signal", [0.1, 0.2]))
    assert isinstance(normalized, pl.DataFrame)
    assert normalized.columns == ["signal"]


def test_lazy_frame_is_only_collected_explicitly() -> None:
    source = pl.DataFrame({"value": [1.0]}).lazy()
    assert isinstance(to_polars(source, collect=True), pl.DataFrame)


def test_numpy_requires_schema_for_two_dimensions() -> None:
    values = np.array([[1.0, 2.0]])
    with pytest.raises(DataContractError, match="explicit schema"):
        to_polars(values)

    frame = to_polars(values, schema=["signal", "forward_return"])
    assert isinstance(frame, pl.DataFrame)
    assert frame.columns == ["signal", "forward_return"]


def test_missing_required_columns_are_reported() -> None:
    frame = pl.DataFrame({"signal": [0.2]})
    with pytest.raises(DataContractError, match="instrument, time"):
        require_columns(frame, ["time", "instrument", "signal"])


def test_optional_arrow_failure_is_wrapped_as_a_data_contract_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_arrow(_: object) -> pl.DataFrame:
        raise ModuleNotFoundError("pyarrow is not installed")

    monkeypatch.setattr(pl, "from_arrow", missing_arrow)

    with pytest.raises(DataContractError, match=r"unsupported dataframe input: builtins\.list"):
        to_polars([1.0, 2.0])
