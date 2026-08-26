from __future__ import annotations

import math

import pytest

from lacuna.signal import fit_decay
from lacuna.types import AnalysisResult, FindingState, ResultMetadata


def _decay_evidence(
    *,
    periods: int = 24,
    horizons: tuple[int, ...] = (1, 2, 4, 8),
    amplitude: float = 0.12,
    tau: float = 4.0,
    direction: float = 1.0,
    flat: float | None = None,
) -> AnalysisResult:
    rows = []
    for period in range(periods):
        period_scale = 1.0 + 0.02 * math.sin(period)
        for horizon in horizons:
            value = flat if flat is not None else amplitude * math.exp(-horizon / tau)
            rows.append(
                {
                    "observation_time": period,
                    "horizon": f"{horizon}D",
                    "ic": direction * value * period_scale,
                }
            )
    return AnalysisResult(
        metadata=ResultMetadata(method="signal.decay"),
        metrics={"n_horizons": len(horizons)},
        tables={"ic_by_period_horizon": tuple(rows)},
    )


@pytest.mark.optional_dependency(reason="SciPy is provided by the statistics extra")
def test_fit_decay_recovers_known_half_life_and_is_seed_deterministic() -> None:
    pytest.importorskip("scipy")
    source = _decay_evidence()
    first = fit_decay(source, resamples=100, seed=42, minimum_r_squared=0.99)
    second = fit_decay(source, resamples=100, seed=42, minimum_r_squared=0.99)

    assert first.metrics["tau"] == pytest.approx(4.0, rel=0.03)
    assert first.metrics["half_life"] == pytest.approx(4.0 * math.log(2.0), rel=0.03)
    assert first.metrics == second.metrics
    assert first.tables == second.tables
    assert first.metadata.parameters["root_entropy"] == 42
    assert {finding.state for finding in first.findings} == {FindingState.PASS}


@pytest.mark.optional_dependency(reason="SciPy is provided by the statistics extra")
def test_fit_decay_handles_expected_negative_direction() -> None:
    pytest.importorskip("scipy")
    result = fit_decay(
        _decay_evidence(direction=-1.0),
        expected_direction="negative",
        resamples=100,
        seed=7,
    )
    assert result.metrics["half_life"] is not None


def test_fit_decay_with_inadequate_support_returns_unknown_not_a_number() -> None:
    result = fit_decay(_decay_evidence(periods=19), resamples=100, seed=1)
    assert result.metrics["half_life"] is None
    assert result.findings[0].state == FindingState.UNKNOWN
    assert result.findings[0].code == "DECAY_SUPPORT_INSUFFICIENT"


@pytest.mark.optional_dependency(reason="SciPy is provided by the statistics extra")
def test_fit_decay_rejects_zero_or_nonidentifiable_curves() -> None:
    pytest.importorskip("scipy")
    zero = fit_decay(_decay_evidence(flat=0.0), resamples=100, seed=1)
    assert zero.metrics["half_life"] is None
    assert zero.findings[0].code == "DECAY_DIRECTION_INVALID"

    flat = fit_decay(_decay_evidence(flat=0.1), resamples=100, seed=1)
    assert flat.metrics["half_life"] is None
    assert flat.findings[0].code == "DECAY_FIT_NOT_IDENTIFIABLE"


def test_fit_decay_requires_joint_period_tables_and_valid_configuration() -> None:
    incomplete = AnalysisResult(
        metadata=ResultMetadata(method="signal.decay"),
        metrics={},
    )
    result = fit_decay(incomplete, resamples=100, seed=2)
    assert result.findings[0].code == "DECAY_JOINT_PERIOD_EVIDENCE_MISSING"

    with pytest.raises(ValueError, match="resamples"):
        fit_decay(_decay_evidence(), resamples=99)
