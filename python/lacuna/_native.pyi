"""Types for the PyO3 extension."""

from collections.abc import Sequence

def version() -> str: ...
def checked_mean(values: Sequence[float]) -> float: ...
def grouped_rank_ic(
    signal: Sequence[float],
    labels: Sequence[float],
    offsets: Sequence[int],
) -> list[float | None]: ...
def bootstrap_means(
    values: Sequence[float],
    indices: Sequence[int],
    offsets: Sequence[int],
) -> list[float]: ...
def interval_purge(
    train_starts: Sequence[int],
    train_ends: Sequence[int],
    test_starts: Sequence[int],
    test_ends: Sequence[int],
) -> list[bool]: ...
