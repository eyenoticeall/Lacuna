from __future__ import annotations

import numpy as np
import pytest

from lacuna._carriers import CostComponentBatch, ResampleBatch
from lacuna.exceptions import DataContractError


def test_cost_component_batch_preserves_names_values_and_unknown_rows() -> None:
    batch = CostComponentBatch.from_components(
        {"commission": (1.0, None, 3.0), "spread": (0.5, 0.5, 0.5)},
        row_count=3,
    )

    assert batch.names == ("commission", "spread")
    assert batch.values.flags.c_contiguous
    assert batch.validity.flags.c_contiguous
    assert batch.values.flags.writeable is False
    assert batch.validity.flags.writeable is False
    assert batch.row_validity.tolist() == [True, False, True]
    assert batch.row_totals.tolist() == pytest.approx([1.5, 0.5, 3.5])
    assert batch.component_totals() == {"commission": None, "spread": 1.5}


def test_empty_cost_component_batch_treats_every_row_as_known() -> None:
    batch = CostComponentBatch.from_components({}, row_count=4)

    assert batch.values.shape == (0, 4)
    assert batch.row_validity.tolist() == [True, True, True, True]
    assert batch.row_totals.tolist() == [0.0, 0.0, 0.0, 0.0]


def test_cost_component_batch_rejects_misalignment_and_invalid_status_codes() -> None:
    with pytest.raises(DataContractError, match="align"):
        CostComponentBatch.from_components({"commission": (1.0,)}, row_count=2)

    with pytest.raises(DataContractError, match="0 or 1"):
        CostComponentBatch(
            names=("commission",),
            values=np.zeros((1, 1), dtype=np.float64),
            validity=np.array([[2]], dtype=np.uint8),
        )


def test_resample_batch_flattens_samples_and_validates_offsets() -> None:
    values = np.arange(12, dtype=np.float64).reshape(4, 3)
    batch = ResampleBatch.from_samples(
        values,
        (np.array([0, 2, 3]), np.array([1, 1, 0])),
    )

    assert batch.indices.tolist() == [0, 2, 3, 1, 1, 0]
    assert batch.offsets.tolist() == [0, 3, 6]
    assert batch.resamples == 2
    assert batch.values.flags.writeable is False
    assert batch.indices.flags.writeable is False

    with pytest.raises(DataContractError, match="offsets"):
        ResampleBatch(
            values=values,
            indices=np.array([0, 1], dtype=np.int64),
            offsets=np.array([0, 2, 1], dtype=np.int64),
        )
