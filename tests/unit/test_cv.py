from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from lacuna.cv import PurgedKFold, WalkForward
from lacuna.exceptions import DataContractError, MethodContractError


def _panel(periods: int = 10, instruments: int = 2) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "time": [period for period in range(periods) for _ in range(instruments)],
            "instrument": [
                f"asset-{instrument}" for _ in range(periods) for instrument in range(instruments)
            ],
        }
    )


def test_expanding_walk_forward_has_exact_chronological_folds() -> None:
    result = WalkForward(train=3, test=2, step=2).split(_panel())
    assert len(result.folds) == 3
    assert [len(fold.train_indices) for fold in result.folds] == [6, 10, 14]
    assert [len(fold.test_indices) for fold in result.folds] == [4, 4, 4]
    assert max(result.folds[0].train_indices) < min(result.folds[0].test_indices)
    assert result.evidence.metadata.parameters["shuffle"] is False


def test_rolling_walk_forward_keeps_fixed_training_width() -> None:
    result = WalkForward(train=3, test=2, step=2, mode="rolling").split(_panel())
    assert [len(fold.train_indices) for fold in result.folds] == [6, 6, 6]


def test_walk_forward_can_include_final_incomplete_window() -> None:
    complete = WalkForward(train=3, test=3, step=3).split(_panel(periods=8))
    incomplete = WalkForward(train=3, test=3, step=3, allow_incomplete=True).split(
        _panel(periods=8)
    )
    assert len(complete.folds) == 1
    assert len(incomplete.folds) == 2
    assert len(incomplete.folds[-1].test_indices) == 4


def test_calendar_walk_forward_uses_calendar_boundaries() -> None:
    frame = pl.DataFrame(
        {
            "time": [date(2025, month, 1) for month in range(1, 13) for _ in range(2)],
            "instrument": ["A", "B"] * 12,
        }
    )
    result = WalkForward(train="3M", test="2M", step="2M").split(frame)
    assert len(result.folds) == 4
    assert result.folds[0].train_indices == (0, 1, 2, 3, 4, 5)
    assert result.folds[0].test_indices == (6, 7, 8, 9)


def _intervals() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "observation_time": list(range(6)),
            "label_start": list(range(6)),
            "label_end": [value + 2 for value in range(6)],
        }
    )


def test_purged_kfold_removes_every_overlapping_training_interval() -> None:
    result = PurgedKFold(n_splits=3, use_native=False).split(_intervals())
    first = result.folds[0]
    assert first.test_indices == (0, 1)
    assert first.purged_indices == (2,)
    assert first.train_indices == (3, 4, 5)

    frame = _intervals()
    for fold in result.folds:
        for train_index in fold.train_indices:
            train = frame.row(train_index, named=True)
            for test_index in fold.test_indices:
                test = frame.row(test_index, named=True)
                assert not (
                    train["label_start"] < test["label_end"]
                    and train["label_end"] > test["label_start"]
                )


def test_boundary_touching_intervals_are_not_purged() -> None:
    frame = pl.DataFrame(
        {
            "observation_time": [0, 1, 2, 3],
            "label_start": [0, 1, 2, 3],
            "label_end": [1, 2, 3, 4],
        }
    )
    first = PurgedKFold(n_splits=2, use_native=False).split(frame).folds[0]
    assert first.purged_indices == ()
    assert first.train_indices == (2, 3)


def test_embargo_is_separate_from_purging() -> None:
    frame = pl.DataFrame(
        {
            "observation_time": list(range(6)),
            "label_start": list(range(6)),
            "label_end": [value + 1 for value in range(6)],
        }
    )
    first = PurgedKFold(n_splits=3, embargo=1, use_native=False).split(frame).folds[0]
    assert first.purged_indices == ()
    assert first.embargoed_indices == (2,)
    assert first.train_indices == (3, 4, 5)


def test_native_and_reference_purge_paths_match() -> None:
    native = PurgedKFold(n_splits=3, embargo=1, use_native=True).split(_intervals())
    reference = PurgedKFold(n_splits=3, embargo=1, use_native=False).split(_intervals())
    assert native.folds == reference.folds
    assert native.evidence.metadata.parameters["backend"] == "rust_native"


def test_splitters_reject_invalid_configuration_and_intervals() -> None:
    with pytest.raises(MethodContractError):
        WalkForward(train=0, test=1, step=1)
    with pytest.raises(MethodContractError, match="same duration convention"):
        WalkForward(train="1Y", test=2, step=1)
    with pytest.raises(MethodContractError):
        PurgedKFold(n_splits=1)

    invalid = _intervals().with_columns(
        pl.when(pl.col("observation_time") == 0)
        .then(pl.col("label_start"))
        .otherwise(pl.col("label_end"))
        .alias("label_end")
    )
    with pytest.raises(DataContractError, match="label_start < label_end"):
        PurgedKFold(n_splits=2).split(invalid)


def test_lazy_input_is_materialized_deliberately_and_recorded() -> None:
    result = WalkForward(train=3, test=2, step=2).split(_panel().lazy())
    input_metadata = result.evidence.metadata.parameters["input"]
    assert input_metadata["materialized"] is True  # type: ignore[index]
