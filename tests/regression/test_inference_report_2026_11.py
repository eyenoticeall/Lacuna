"""Regression tests for Sharpe-inference findings reported against v0.14.1."""

from __future__ import annotations

import numpy as np

from lacuna.types import FindingState
from lacuna.validation import sharpe_inference


def _selected_from_null(seed: int, trials: int = 50, periods: int = 500) -> tuple[object, ...]:
    rng = np.random.default_rng(seed)
    returns = rng.normal(0.0, 0.01, size=(trials, periods))
    sharpes = returns.mean(axis=1) / returns.std(axis=1, ddof=1)
    best = int(np.argmax(sharpes))
    return returns[best], sharpes


def test_selected_null_strategy_cannot_show_only_an_undeflated_pass() -> None:
    """With a declared trial family the DSR verdict must appear as a finding.

    The best of 50 zero-edge strategies passes the PSR finding; the findings used to stop
    there even though ``deflated_sharpe_ratio`` showed selection explains the result.
    """

    returns, sharpes = _selected_from_null(20_261_121)
    result = sharpe_inference(returns, trial_sharpes=sharpes, confidence_level=0.95)
    states = {finding.code: finding.state for finding in result.findings}

    assert states["SHARPE_EXCEEDS_BENCHMARK"] is FindingState.PASS
    assert states["DEFLATED_SHARPE_UNCERTAIN"] is FindingState.WARN
    assert result.metrics["deflated_sharpe_ratio"] < 0.95  # type: ignore[operator]
    assert result.metadata.method_version == 2


def test_deflated_finding_passes_for_a_strong_selected_strategy() -> None:
    rng = np.random.default_rng(7)
    strong = rng.normal(0.004, 0.01, size=2_000)
    observed = float(strong.mean() / strong.std(ddof=1))
    family = np.array([observed, 0.01, -0.02, 0.0, 0.015])
    result = sharpe_inference(strong, trial_sharpes=family, confidence_level=0.95)
    states = {finding.code: finding.state for finding in result.findings}

    assert states["DEFLATED_SHARPE_SUPPORTED"] is FindingState.PASS


def test_no_deflated_finding_without_a_trial_family() -> None:
    rng = np.random.default_rng(11)
    result = sharpe_inference(rng.normal(0.001, 0.01, size=500))
    codes = {finding.code for finding in result.findings}

    assert not {"DEFLATED_SHARPE_SUPPORTED", "DEFLATED_SHARPE_UNCERTAIN"} & codes
