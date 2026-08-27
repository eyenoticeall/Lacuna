"""Private execution-budget resolution for bounded analytical work."""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import polars as pl

from lacuna.config import Config, ThreadCount, get_config
from lacuna.exceptions import ConfigurationError

_DEFAULT_WORKSPACE_BYTES = 64 * 1024 * 1024
_MEMORY_PATTERN = re.compile(
    r"^(?P<amount>[0-9]+(?:\.[0-9]+)?)\s*(?P<unit>B|KB|MB|GB|TB|KIB|MIB|GIB|TIB)?$",
    re.IGNORECASE,
)
_MEMORY_FACTORS = {
    "B": 1,
    "KB": 1_000,
    "MB": 1_000_000,
    "GB": 1_000_000_000,
    "TB": 1_000_000_000_000,
    "KIB": 1024,
    "MIB": 1024**2,
    "GIB": 1024**3,
    "TIB": 1024**4,
}


@dataclass(frozen=True, slots=True)
class ResolvedExecutionBudget:
    """Immutable resource decision made before a bounded allocation."""

    memory_limit_bytes: int | None
    required_fixed_allocation_bytes: int
    per_item_workspace_bytes: int
    per_batch_workspace_bytes: int
    selected_batch_size: int
    total_items: int
    requested_threads: ThreadCount
    observed_polars_threads: int
    observed_blas_threads: tuple[tuple[str, str | None], ...]
    native_threads: int
    backend: str
    dispatch_reason: str


def parse_memory_limit(value: str | None) -> int | None:
    """Parse a configured byte limit without guessing an undocumented unit."""

    if value is None:
        return None
    normalized = value.strip()
    match = _MEMORY_PATTERN.fullmatch(normalized)
    if match is None:
        raise ConfigurationError(
            "memory_limit must be bytes or use B, KB, MB, GB, TB, KiB, MiB, GiB, or TiB"
        )
    try:
        amount = Decimal(match.group("amount"))
    except InvalidOperation as error:  # pragma: no cover - guarded by the regular expression
        raise ConfigurationError(
            "memory_limit must contain a finite non-negative amount"
        ) from error
    unit = (match.group("unit") or "B").upper()
    resolved = int(amount * _MEMORY_FACTORS[unit])
    if resolved < 1 or resolved > sys.maxsize:
        raise ConfigurationError("memory_limit must resolve to between 1 byte and sys.maxsize")
    return resolved


def _checked_bytes(value: int, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ConfigurationError(f"{name} must be a non-negative integer byte count")
    if value > sys.maxsize:
        raise ConfigurationError(f"{name} exceeds the supported allocation range")
    return value


def resolve_execution_budget(
    *,
    total_items: int,
    required_fixed_allocation_bytes: int,
    per_item_workspace_bytes: int,
    backend: str,
    dispatch_reason: str,
    workspace_cap_bytes: int | None = None,
    configuration: Config | None = None,
) -> ResolvedExecutionBudget:
    """Resolve the largest safe batch while keeping third-party pools observable."""

    items = _checked_bytes(total_items, name="total_items")
    fixed = _checked_bytes(
        required_fixed_allocation_bytes,
        name="required_fixed_allocation_bytes",
    )
    per_item = _checked_bytes(per_item_workspace_bytes, name="per_item_workspace_bytes")
    cap = (
        _DEFAULT_WORKSPACE_BYTES
        if workspace_cap_bytes is None
        else _checked_bytes(workspace_cap_bytes, name="workspace_cap_bytes")
    )
    if not backend.strip() or not dispatch_reason.strip():
        raise ConfigurationError("backend and dispatch_reason must be non-empty")

    resolved_config = configuration or get_config()
    memory_limit = parse_memory_limit(resolved_config.memory_limit)
    if memory_limit is not None and fixed > memory_limit:
        raise ConfigurationError(
            "memory_limit cannot fit the required fixed output allocation "
            f"({fixed} bytes required, {memory_limit} bytes configured)"
        )
    available_workspace = cap
    if memory_limit is not None:
        available_workspace = min(available_workspace, memory_limit - fixed)

    if items == 0:
        batch_size = 0
    elif per_item == 0:
        batch_size = items
    else:
        batch_size = min(items, available_workspace // per_item)
        if batch_size < 1:
            raise ConfigurationError(
                "memory_limit cannot fit one batch item after required fixed allocations "
                f"({per_item} workspace bytes required per item)"
            )

    workspace = batch_size * per_item
    return ResolvedExecutionBudget(
        memory_limit_bytes=memory_limit,
        required_fixed_allocation_bytes=fixed,
        per_item_workspace_bytes=per_item,
        per_batch_workspace_bytes=workspace,
        selected_batch_size=batch_size,
        total_items=items,
        requested_threads=resolved_config.threads,
        observed_polars_threads=pl.thread_pool_size(),
        observed_blas_threads=tuple(
            (name, os.environ.get(name))
            for name in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_NUM_THREADS")
        ),
        native_threads=1,
        backend=backend,
        dispatch_reason=dispatch_reason,
    )
