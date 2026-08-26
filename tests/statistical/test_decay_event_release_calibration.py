from __future__ import annotations

import math
import os

import numpy as np
import polars as pl
import pytest

from lacuna.events import EventWindowResult, event_response
from lacuna.signal import fit_decay
from lacuna.types import AnalysisResult, ResultMetadata

pytestmark = pytest.mark.optional_dependency(
    reason="decay calibration requires the statistics extra"
)


def _simulation_count() -> int:
    raw = os.environ.get("LACUNA_RELEASE_CALIBRATION_SIMULATIONS", "8")
    count = int(raw)
    if count < 1:
        raise ValueError("LACUNA_RELEASE_CALIBRATION_SIMULATIONS must be positive")
    return count


def _decay_source(generator: np.random.Generator, *, tau: float) -> AnalysisResult:
    horizons = (1, 2, 4, 8)
    rows = []
    for period in range(40):
        common_shock = generator.normal(0.0, 0.08)
        for horizon in horizons:
            idiosyncratic = generator.normal(0.0, 0.08)
            value = 0.12 * math.exp(-horizon / tau) * math.exp(common_shock + idiosyncratic)
            rows.append(
                {
                    "observation_time": period,
                    "horizon": f"{horizon}D",
                    "ic": value,
                }
            )
    return AnalysisResult(
        metadata=ResultMetadata(method="signal.decay"),
        metrics={"n_horizons": len(horizons)},
        tables={"ic_by_period_horizon": tuple(rows)},
    )


def _event_windows(generator: np.random.Generator) -> EventWindowResult:
    rows = []
    for cluster in range(30):
        cluster_shock = generator.normal(0.0, 0.01)
        path_noise = generator.normal(0.0, 0.02, size=2)
        event_id = f"event-{cluster}"
        rows.extend(
            (
                {
                    "event_id": event_id,
                    "instrument": f"asset-{cluster}",
                    "aligned_anchor_time": cluster,
                    "offset": -1,
                    "response": float(cluster_shock + path_noise[0]),
                },
                {
                    "event_id": event_id,
                    "instrument": f"asset-{cluster}",
                    "aligned_anchor_time": cluster,
                    "offset": 0,
                    "response": 0.0,
                },
                {
                    "event_id": event_id,
                    "instrument": f"asset-{cluster}",
                    "aligned_anchor_time": cluster,
                    "offset": 1,
                    "response": float(cluster_shock + path_noise[1]),
                },
            )
        )
    return EventWindowResult(
        _frame=pl.DataFrame(rows),
        evidence=AnalysisResult(
            metadata=ResultMetadata(
                method="events.event_windows",
                parameters={"before": 1, "after": 1},
            ),
            metrics={"n_events": 30},
        ),
    )


def test_fixed_seed_decay_and_event_interval_calibration() -> None:
    pytest.importorskip("scipy")
    simulations = _simulation_count()
    generator = np.random.default_rng(20260826)
    true_half_life = 4.0 * math.log(2.0)
    decay_covered = 0
    decay_identified = 0
    event_pointwise_covered = 0
    simultaneous_false_positives = 0

    for simulation in range(simulations):
        decay = fit_decay(
            _decay_source(generator, tau=4.0),
            resamples=100,
            expected_block_length=3,
            seed=10_000 + simulation,
            minimum_r_squared=0.5,
        )
        lower = decay.metrics["half_life_lower"]
        upper = decay.metrics["half_life_upper"]
        if isinstance(lower, int | float) and isinstance(upper, int | float):
            decay_identified += 1
            decay_covered += int(float(lower) <= true_half_life <= float(upper))

        event = event_response(
            _event_windows(generator),
            resamples=100,
            expected_block_length=3,
            seed=20_000 + simulation,
        )
        rows = {int(row["offset"]): row for row in event.table("event_response")}
        event_pointwise_covered += int(
            float(rows[1]["pointwise_lower"]) <= 0.0 <= float(rows[1]["pointwise_upper"])
        )
        simultaneous_false_positives += int(
            any(
                row["simultaneous_lower"] is not None
                and not (
                    float(row["simultaneous_lower"]) <= 0.0 <= float(row["simultaneous_upper"])
                )
                for offset, row in rows.items()
                if offset != 0
            )
        )

    assert decay_identified >= math.floor(simulations * 0.9)
    if simulations >= 100:
        decay_coverage = decay_covered / decay_identified
        event_coverage = event_pointwise_covered / simulations
        family_false_positive_rate = simultaneous_false_positives / simulations
        # Fixed-seed Monte Carlo bounds are intentionally wider than sampling error alone because
        # these finite-sample procedures estimate their own block-bootstrap distributions.
        assert 0.85 <= decay_coverage <= 0.995
        assert 0.85 <= event_coverage <= 0.995
        assert family_false_positive_rate <= 0.15
