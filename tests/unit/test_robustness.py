from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime

import pytest

from lacuna.exceptions import DataContractError, MethodContractError
from lacuna.experiment import ExperimentRegistry
from lacuna.robustness import (
    PerturbationSpec,
    Subperiod,
    UniverseScenario,
    continuous_perturbation,
    subperiod_analysis,
    universe_perturbation,
)
from lacuna.types import AnalysisResult, JsonValue, ResultMetadata


def _result(**metrics: JsonValue) -> AnalysisResult:
    return AnalysisResult(
        metadata=ResultMetadata(method="test.evaluator", input_fingerprint="input:v1"),
        metrics=metrics,
    )


def test_continuous_perturbation_is_seeded_and_reproducible() -> None:
    def evaluate(parameters: Mapping[str, JsonValue]) -> AnalysisResult:
        value = float(parameters["fast"]) + float(parameters["slow"])  # type: ignore[arg-type]
        return _result(score=value)

    kwargs = {
        "selected_parameters": {"fast": 5, "slow": 20.0, "label": "baseline"},
        "perturbations": {
            "fast": PerturbationSpec(scale=2.0, lower=1, integer=True),
            "slow": PerturbationSpec(distribution="lognormal", scale=0.1, lower=1),
        },
        "objective": "score",
        "evaluator_name": "strategy.score",
        "sample_id": "sample:validation",
        "code_id": "git:abc123",
        "draws": 25,
        "seed": 42,
    }
    first = continuous_perturbation(evaluate, **kwargs)  # type: ignore[arg-type]
    second = continuous_perturbation(evaluate, **kwargs)  # type: ignore[arg-type]

    assert first.table("perturbations") == second.table("perturbations")
    assert first.metadata.input_fingerprint == second.metadata.input_fingerprint
    assert first.metrics["accepted_samples"] == 25
    assert first.metadata.seed == 42


def test_continuous_perturbation_reports_constraint_rejections_and_failures() -> None:
    registry = ExperimentRegistry("perturbation")

    def evaluate(parameters: Mapping[str, JsonValue]) -> AnalysisResult:
        if float(parameters["fast"]) == 5.0:  # type: ignore[arg-type]
            raise ArithmeticError("must not be recorded")
        return _result(score=float(parameters["slow"]))  # type: ignore[arg-type]

    result = continuous_perturbation(
        evaluate,
        selected_parameters={"fast": 5, "slow": 6},
        perturbations={
            "fast": PerturbationSpec(distribution="uniform", scale=5, lower=1, integer=True),
            "slow": PerturbationSpec(distribution="uniform", scale=5, lower=1, integer=True),
        },
        objective="score",
        evaluator_name="strategy.score",
        sample_id="sample:validation",
        code_id="git:abc123",
        draws=40,
        seed=7,
        constraint=lambda parameters: float(parameters["fast"]) < float(parameters["slow"]),  # type: ignore[arg-type]
        constraint_name="fast_lt_slow:v1",
        registry=registry,
    )

    assert int(result.metrics["attempted_samples"]) > 40  # type: ignore[arg-type]
    assert float(result.metrics["rejection_rate"]) > 0.0  # type: ignore[arg-type]
    assert len(registry.attempts()) == 40
    assert "must not be recorded" not in registry.to_result().to_json()
    assert "PERTURBATION_EVALUATION_FAILURES" in {finding.code for finding in result.findings}


def test_continuous_perturbation_exposes_acceptance_shortfall() -> None:
    result = continuous_perturbation(
        lambda _: _result(score=1.0),
        selected_parameters={"window": 10},
        perturbations={"window": PerturbationSpec(scale=1.0)},
        objective="score",
        evaluator_name="strategy.score",
        sample_id="sample:validation",
        code_id="git:abc123",
        draws=2,
        max_attempts=2,
        constraint=lambda _: False,
        constraint_name="impossible:v1",
    )

    assert result.metrics["accepted_samples"] == 0
    assert "PERTURBATION_ACCEPTANCE_SHORTFALL" in {finding.code for finding in result.findings}


def test_continuous_perturbation_validates_contracts() -> None:
    with pytest.raises(MethodContractError, match="constraint_name"):
        continuous_perturbation(
            lambda _: _result(score=1.0),
            selected_parameters={"window": 10},
            perturbations={"window": PerturbationSpec(scale=1.0)},
            objective="score",
            evaluator_name="strategy.score",
            sample_id="sample:validation",
            code_id="git:abc123",
            constraint=lambda _: True,
        )
    with pytest.raises(DataContractError, match="finite and numeric"):
        continuous_perturbation(
            lambda _: _result(score=1.0),
            selected_parameters={"window": "ten"},
            perturbations={"window": PerturbationSpec(scale=1.0)},
            objective="score",
            evaluator_name="strategy.score",
            sample_id="sample:validation",
            code_id="git:abc123",
        )


def test_subperiod_analysis_preserves_windows_support_and_concentration() -> None:
    periods = [
        Subperiod("early", date(2020, 1, 1), date(2021, 1, 1), "sample:early"),
        Subperiod("middle", date(2021, 1, 1), date(2022, 1, 1), "sample:middle"),
        Subperiod("late", date(2022, 1, 1), date(2023, 1, 1), "sample:late"),
    ]
    values = {
        "early": (1.0, 100, 90.0),
        "middle": (-0.2, 80, 5.0),
        "late": (0.4, 70, 5.0),
    }

    result = subperiod_analysis(
        lambda period: _result(
            score=values[period.name][0],
            observations=values[period.name][1],
            pnl=values[period.name][2],
        ),
        periods=periods,
        objective="score",
        sample_count_metric="observations",
        outcome_metric="pnl",
        evaluator_name="strategy.period_score",
        code_id="git:abc123",
    )

    table = result.table("subperiods")
    assert [row["start"] for row in table] == [  # type: ignore[index, union-attr]
        "2020-01-01",
        "2021-01-01",
        "2022-01-01",
    ]
    assert result.metrics["sign_consistency"] == pytest.approx(2 / 3)
    assert result.metrics["top_absolute_outcome_share"] == pytest.approx(0.9)
    assert {finding.code for finding in result.findings} >= {
        "SUBPERIOD_SIGN_INSTABILITY",
        "SUBPERIOD_OUTCOME_CONCENTRATION",
    }


def test_subperiod_overlap_and_failed_periods_remain_explicit() -> None:
    periods = [
        Subperiod("first", date(2020, 1, 1), date(2021, 7, 1), "sample:first"),
        Subperiod("second", date(2021, 1, 1), date(2022, 1, 1), "sample:second"),
    ]

    def evaluate(period: Subperiod) -> AnalysisResult:
        if period.name == "second":
            raise RuntimeError("not recorded")
        return _result(score=0.5, observations=100)

    result = subperiod_analysis(
        evaluate,
        periods=periods,
        objective="score",
        sample_count_metric="observations",
        evaluator_name="strategy.period_score",
        code_id="git:abc123",
    )

    assert result.metrics["overlap_count"] == 1
    assert result.metrics["failed_periods"] == 1
    assert {finding.code for finding in result.findings} >= {
        "SUBPERIOD_OVERLAP",
        "SUBPERIOD_EVALUATION_FAILURES",
    }


def test_temporal_contracts_reject_naive_or_reversed_windows() -> None:
    with pytest.raises(MethodContractError, match="timezone-aware"):
        Subperiod(
            "naive",
            datetime(2020, 1, 1),
            datetime(2021, 1, 1),
            "sample:naive",
        )
    with pytest.raises(MethodContractError, match="start < end"):
        Subperiod("reversed", date(2021, 1, 1), date(2020, 1, 1), "sample:reversed")


def test_universe_perturbation_preserves_composition_and_eligibility_time() -> None:
    as_of = datetime(2024, 1, 2, tzinfo=UTC)
    universes = [
        UniverseScenario(
            "baseline",
            "membership:base",
            as_of,
            ("A", "B", "C"),
            "historical eligible set",
        ),
        UniverseScenario(
            "liquid",
            "membership:liquid",
            as_of,
            ("B", "C"),
            "top liquidity threshold",
        ),
        UniverseScenario(
            "current",
            "membership:current",
            as_of,
            ("C", "D"),
            "current constituents",
            point_in_time=False,
        ),
    ]

    result = universe_perturbation(
        lambda universe: _result(
            score=float(len(universe.instrument_ids)),
            observations=len(universe.instrument_ids) * 10,
        ),
        universes=universes,
        baseline="baseline",
        objective="score",
        sample_count_metric="observations",
        evaluator_name="strategy.universe_score",
        code_id="git:abc123",
    )

    rows = result.table("universes")
    assert rows[1]["retained_baseline_fraction"] == pytest.approx(2 / 3)  # type: ignore[index]
    assert rows[2]["composition_jaccard"] == pytest.approx(0.25)  # type: ignore[index]
    assert rows[0]["as_of"] == "2024-01-02T00:00:00Z"  # type: ignore[index]
    assert rows[1]["instrument_ids"] == ["B", "C"]  # type: ignore[index]
    assert "UNIVERSE_RETROSPECTIVE_MEMBERSHIP" in {finding.code for finding in result.findings}


def test_universe_contracts_require_stable_unique_membership() -> None:
    with pytest.raises(MethodContractError, match="unique"):
        UniverseScenario(
            "duplicate",
            "membership:duplicate",
            date(2024, 1, 1),
            ("A", "A"),
            "invalid",
        )
    universe = UniverseScenario(
        "baseline",
        "membership:base",
        date(2024, 1, 1),
        ("A",),
        "historical",
    )
    with pytest.raises(MethodContractError, match="baseline"):
        universe_perturbation(
            lambda _: _result(score=1.0, observations=1),
            universes=[universe],
            baseline="missing",
            objective="score",
            sample_count_metric="observations",
            evaluator_name="strategy.universe_score",
            code_id="git:abc123",
        )
