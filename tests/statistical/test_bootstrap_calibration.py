from __future__ import annotations

import numpy as np

from lacuna.validation import bootstrap


def test_moving_block_interval_has_reasonable_fixed_seed_ar1_coverage() -> None:
    generator = np.random.default_rng(20260826)
    covered = 0
    simulations = 24
    for simulation in range(simulations):
        innovations = generator.normal(size=120)
        values = np.empty(120)
        values[0] = innovations[0]
        for index in range(1, values.size):
            values[index] = 0.6 * values[index - 1] + innovations[index]
        result = bootstrap(
            values,
            method="moving",
            block_length=8,
            resamples=300,
            confidence_level=0.90,
            seed=simulation,
            use_native=False,
        )
        lower = float(result.metrics["confidence_lower"])
        upper = float(result.metrics["confidence_upper"])
        covered += int(lower <= 0.0 <= upper)

    # This is a deterministic calibration guard, not a claim of exact nominal
    # finite-sample coverage. A conceptually IID implementation fails it.
    assert covered >= 17
