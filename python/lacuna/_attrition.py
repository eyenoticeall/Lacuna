"""Internal helpers for deterministic row-attrition evidence."""

from __future__ import annotations

from lacuna.exceptions import MethodContractError
from lacuna.types import JsonValue


def attrition_record(
    stage: str,
    reason: str,
    *,
    input_rows: int,
    retained_rows: int,
    policy: str,
) -> dict[str, JsonValue]:
    """Build one exactly reconciling attrition-ledger row."""

    if not stage or not reason or not policy:
        raise MethodContractError("attrition stage, reason, and policy must not be empty")
    if input_rows < 0 or retained_rows < 0 or retained_rows > input_rows:
        raise MethodContractError("attrition row counts must satisfy 0 <= retained <= input")
    excluded_rows = input_rows - retained_rows
    return {
        "stage": stage,
        "reason": reason,
        "input_rows": input_rows,
        "retained_rows": retained_rows,
        "excluded_rows": excluded_rows,
        "excluded_fraction": excluded_rows / input_rows if input_rows else 0.0,
        "policy": policy,
    }


__all__ = ["attrition_record"]
