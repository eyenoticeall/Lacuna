"""Types for the private PyO3 extension."""

import numpy as np
import numpy.typing as npt

def version() -> str: ...
def checked_mean(values: list[float]) -> float: ...
def grouped_rank_ic(
    signal: npt.NDArray[np.float64],
    labels: npt.NDArray[np.float64],
    offsets: npt.NDArray[np.int64],
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.uint8]]: ...
def bootstrap_means(
    values: npt.NDArray[np.float64],
    indices: npt.NDArray[np.int64],
    offsets: npt.NDArray[np.int64],
) -> npt.NDArray[np.float64]: ...
def interval_purge(
    train_starts: npt.NDArray[np.int64],
    train_ends: npt.NDArray[np.int64],
    test_starts: npt.NDArray[np.int64],
    test_ends: npt.NDArray[np.int64],
) -> npt.NDArray[np.uint8]: ...
