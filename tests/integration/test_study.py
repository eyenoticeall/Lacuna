from __future__ import annotations

import json

import numpy as np
import polars as pl
import pytest

from lacuna.cv import PurgedKFold
from lacuna.exceptions import MethodContractError
from lacuna.signal import ic
from lacuna.study import SignalStudy
from lacuna.types import FindingState


def _study_data(periods: int = 28, instruments: int = 6) -> tuple[pl.DataFrame, pl.DataFrame]:
    names = [f"asset-{index}" for index in range(instruments)]
    prices = pl.DataFrame(
        {
            "time": np.tile(np.arange(periods), instruments),
            "instrument": np.repeat(names, periods),
            "close": [
                100.0 * (1.0 + 0.002 * (instrument_index + 1)) ** time
                for instrument_index in range(instruments)
                for time in range(periods)
            ],
            "delisting_return": np.zeros(periods * instruments),
        }
    )
    signal_periods = periods - 3
    signal = pl.DataFrame(
        {
            "time": np.repeat(np.arange(signal_periods), instruments),
            "instrument": np.tile(names, signal_periods),
            "signal": np.tile(np.arange(instruments, dtype=np.float64), signal_periods),
        }
    )
    return signal, prices


def _study() -> SignalStudy:
    signal, prices = _study_data()
    return SignalStudy(
        signal=signal,
        prices=prices,
        horizons=("1D", "2D", "3D"),
        price_adjustment="raw",
        delisting_return="delisting_return",
        quantiles=3,
    )


def test_study_delegates_to_the_functional_signal_api() -> None:
    signal, _ = _study_data()
    study = _study()

    from_study = study.ic(use_native=False)
    functional = ic(signal, study.labels(), use_native=False)

    assert from_study.metrics == functional.metrics
    assert from_study.tables == functional.tables
    assert from_study.findings == functional.findings


def test_signal_study_runs_an_end_to_end_audit(capsys: object) -> None:
    study = _study()
    split = PurgedKFold(n_splits=3, use_native=False).split(study.labels().frame)
    report = study.audit(
        bootstrap_resamples=100,
        seed=41,
        split=split,
        policies={"survivorship_safe": True, "trial_history_available": True},
        use_native=False,
    )

    assert report.metrics["robustness_score"] == 100.0
    assert report.metrics["evidence_coverage"] == 1.0
    assert report.metrics["failure_count"] == 0
    assert report.metrics["unknown_count"] == 0
    states = {finding.code: finding.state for finding in report.findings}
    assert states["PURGED_VALIDATION_SUPPLIED"] == FindingState.PASS
    assert states["TRANSACTION_COST_EVIDENCE"] == FindingState.NOT_APPLICABLE
    assert json.loads(report.to_json())["metadata"]["method"] == "audit.v0_1"
    assert {
        "labels",
        "ic",
        "quantiles",
        "turnover",
        "decay",
        "bootstrap",
        "split",
    }.issubset(report.evidence)
    assert report.table("ic_by_period", source="ic") == report.evidence["ic"].table("ic_by_period")

    report.show()
    output = capsys.readouterr()  # type: ignore[attr-defined]
    assert "# Lacuna audit" in output.out


def test_signal_study_preserves_missing_methodology_as_unknown() -> None:
    signal, prices = _study_data()
    report = SignalStudy(
        signal=signal,
        prices=prices,
        horizons=("1D", "2D", "3D"),
        quantiles=3,
    ).audit(bootstrap_resamples=100, seed=7, use_native=False)

    states = {finding.code: finding.state for finding in report.findings}
    assert states["PRICE_ADJUSTMENT_DECLARED"] == FindingState.UNKNOWN
    assert states["DELISTING_HANDLING_DECLARED"] == FindingState.UNKNOWN
    assert states["PURGED_VALIDATION_SUPPLIED"] == FindingState.UNKNOWN
    assert report.metrics["evidence_coverage"] < 1.0


@pytest.mark.parametrize(
    ("resamples", "seed"),
    [(99, None), (100, -1)],
)
def test_study_validates_bootstrap_configuration_before_analysis(
    resamples: int, seed: int | None
) -> None:
    with pytest.raises(MethodContractError):
        _study().audit(bootstrap_resamples=resamples, seed=seed, use_native=False)


def test_study_retains_caller_supplied_evidence_and_rejects_name_collisions() -> None:
    extra = _study().ic(use_native=False)
    report = _study().audit(
        bootstrap_resamples=100,
        seed=3,
        additional_evidence={"independent_check": extra},
        use_native=False,
    )
    assert report.evidence["independent_check"] is extra

    with pytest.raises(MethodContractError, match="collide"):
        _study().audit(
            bootstrap_resamples=100,
            seed=3,
            additional_evidence={"ic": extra},
            use_native=False,
        )
