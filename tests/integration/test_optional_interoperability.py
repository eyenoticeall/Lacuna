from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from lacuna.adapters import as_sklearn_cv, from_duckdb
from lacuna.cv import WalkForward


def test_duckdb_relation_streams_through_arrow_without_pandas() -> None:
    duckdb = pytest.importorskip("duckdb")
    pytest.importorskip("pyarrow")
    connection = duckdb.connect(":memory:")
    try:
        relation = connection.sql(
            "SELECT time, instrument, CAST(value AS DOUBLE) AS value "
            "FROM (VALUES (1, 'A', 0.10), (2, 'B', -0.20)) "
            "AS observations(time, instrument, value) ORDER BY time"
        )
        result = from_duckdb(
            relation,
            batch_size=1,
            required=("time", "instrument", "value"),
        )
    finally:
        connection.close()

    assert isinstance(result.frame, pl.DataFrame)
    assert result.frame.to_dict(as_series=False) == {
        "time": [1, 2],
        "instrument": ["A", "B"],
        "value": [0.1, -0.2],
    }
    assert result.evidence.metadata.parameters["reader_method"] == "to_arrow_reader"
    assert result.evidence.metadata.parameters["sql_generated"] is False


def test_sklearn_cross_validate_consumes_lacuna_walk_forward_folds() -> None:
    sklearn_model_selection = pytest.importorskip("sklearn.model_selection")
    sklearn_linear_model = pytest.importorskip("sklearn.linear_model")

    X = np.arange(12.0).reshape(-1, 1)
    y = 2.0 * X[:, 0] + 1.0
    intervals = pl.DataFrame({"time": np.arange(12)})
    cv = as_sklearn_cv(
        WalkForward(train=4, test=2, step=2, mode="expanding"),
        intervals,
    )

    scores = sklearn_model_selection.cross_validate(
        sklearn_linear_model.LinearRegression(),
        X,
        y,
        cv=cv,
        scoring="neg_mean_squared_error",
    )

    assert cv.get_n_splits() == 4
    assert scores["test_score"].shape == (4,)
    assert np.allclose(scores["test_score"], 0.0, atol=1e-20)
