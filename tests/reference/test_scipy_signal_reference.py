from __future__ import annotations

import numpy as np
import pytest

from lacuna.signal import ic


@pytest.mark.parametrize("method", ["pearson", "spearman"])
def test_ic_matches_scipy_reference_with_ties(method: str) -> None:
    scipy_stats = pytest.importorskip("scipy.stats")
    signal = np.asarray([0.2, 0.1, 0.1, 0.4, 0.8, 0.5, 0.5, 0.3])
    returns = np.asarray([0.3, -0.2, 0.1, 0.9, 0.4, 0.2, -0.1, 0.0])

    result = ic(signal, returns, method=method, use_native=False)  # type: ignore[arg-type]
    if method == "pearson":
        expected = scipy_stats.pearsonr(signal, returns).statistic
    else:
        expected = scipy_stats.spearmanr(signal, returns).statistic

    assert result.metrics["mean_ic"] == pytest.approx(expected, abs=1e-14)
