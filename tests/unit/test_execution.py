from __future__ import annotations

import pytest

from lacuna._execution import parse_memory_limit, resolve_execution_budget
from lacuna.config import Config
from lacuna.exceptions import ConfigurationError


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ("1024", 1024),
        ("1 KB", 1_000),
        ("1.5MB", 1_500_000),
        ("2 MiB", 2 * 1024**2),
        ("16GB", 16_000_000_000),
    ],
)
def test_parse_memory_limit_uses_explicit_decimal_and_binary_units(
    value: str | None, expected: int | None
) -> None:
    assert parse_memory_limit(value) == expected


@pytest.mark.parametrize("value", ["", "auto", "-1MB", "1XB", "0B"])
def test_parse_memory_limit_rejects_ambiguous_or_invalid_values(value: str) -> None:
    with pytest.raises(ConfigurationError, match="memory_limit"):
        parse_memory_limit(value)


def test_execution_budget_selects_largest_batch_within_explicit_limit() -> None:
    budget = resolve_execution_budget(
        total_items=20,
        required_fixed_allocation_bytes=200,
        per_item_workspace_bytes=100,
        workspace_cap_bytes=10_000,
        backend="numpy",
        dispatch_reason="test reference",
        configuration=Config(memory_limit="750B", threads=2),
    )

    assert budget.memory_limit_bytes == 750
    assert budget.selected_batch_size == 5
    assert budget.per_batch_workspace_bytes == 500
    assert budget.requested_threads == 2
    assert budget.native_threads == 1
    assert dict(budget.observed_blas_threads).keys() == {
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "OMP_NUM_THREADS",
    }


def test_execution_budget_defaults_to_at_most_64_mib_of_workspace() -> None:
    budget = resolve_execution_budget(
        total_items=100,
        required_fixed_allocation_bytes=0,
        per_item_workspace_bytes=1024**2,
        backend="rust_native",
        dispatch_reason="test kernel",
        configuration=Config(),
    )
    assert budget.selected_batch_size == 64
    assert budget.per_batch_workspace_bytes == 64 * 1024**2


def test_execution_budget_rejects_fixed_output_before_batch_allocation() -> None:
    with pytest.raises(ConfigurationError, match="fixed output allocation"):
        resolve_execution_budget(
            total_items=1,
            required_fixed_allocation_bytes=101,
            per_item_workspace_bytes=1,
            backend="numpy",
            dispatch_reason="test reference",
            configuration=Config(memory_limit="100B"),
        )


def test_execution_budget_rejects_when_one_item_cannot_fit() -> None:
    with pytest.raises(ConfigurationError, match="one batch item"):
        resolve_execution_budget(
            total_items=1,
            required_fixed_allocation_bytes=80,
            per_item_workspace_bytes=21,
            backend="numpy",
            dispatch_reason="test reference",
            configuration=Config(memory_limit="100B"),
        )
