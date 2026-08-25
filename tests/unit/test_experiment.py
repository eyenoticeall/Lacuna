from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from lacuna.exceptions import DataContractError, MethodContractError
from lacuna.experiment import AttemptStatus, ExperimentRegistry, canonical_json, fingerprint
from lacuna.types import FindingState


def test_canonical_json_is_order_independent_and_normalizes_time_and_signed_zero() -> None:
    left = {
        "window": 20,
        "nested": {"z": -0.0, "a": datetime(2026, 1, 1, tzinfo=UTC)},
    }
    right = {
        "nested": {
            "a": datetime(2026, 1, 1, 8, tzinfo=timezone(timedelta(hours=8))),
            "z": 0.0,
        },
        "window": 20,
    }

    assert canonical_json(left) == canonical_json(right)
    assert fingerprint(left, namespace="trial") == fingerprint(right, namespace="trial")


@pytest.mark.parametrize(
    "value, message",
    [
        ({"value": float("nan")}, "NaN or infinity"),
        ({"value": float("inf")}, "NaN or infinity"),
        ({"value": {1, 2}}, "unordered set"),
        ({"value": lambda: None}, "opaque callable"),
        ({"api_key": "secret"}, "credential-bearing"),
        ({1: "value"}, "non-string mapping key"),
        ({"time": datetime(2026, 1, 1)}, "timezone-naive"),
    ],
)
def test_canonical_json_rejects_ambiguous_or_sensitive_values(value: object, message: str) -> None:
    with pytest.raises(DataContractError, match=message):
        canonical_json(value)


def test_fingerprint_requires_namespace_and_separates_domains() -> None:
    value = {"lookback": 20}

    assert fingerprint(value, namespace="trial") != fingerprint(value, namespace="dataset")
    with pytest.raises(MethodContractError, match="namespace"):
        fingerprint(value, namespace="")


def test_registry_preserves_failed_retry_and_immutable_correction() -> None:
    registry = ExperimentRegistry("momentum")
    failed = registry.record(
        parameters={"lookback": 20},
        status=AttemptStatus.FAILED,
        error_category="NumericalError",
        method="strategy.evaluate",
        data_fingerprint="dataset:one",
        code_fingerprint="commit:one",
    )
    retry = registry.record(
        parameters={"lookback": 20},
        metric=1.25,
        method="strategy.evaluate",
        data_fingerprint="dataset:one",
        code_fingerprint="commit:one",
    )
    correction = registry.record(
        parameters={"lookback": 20},
        metric=1.20,
        method="strategy.evaluate",
        data_fingerprint="dataset:one",
        code_fingerprint="commit:one",
        supersedes_attempt_id=retry.attempt_id,
        supersedes_reason="Corrected upstream input manifest",
    )

    assert failed.trial_id == retry.trial_id == correction.trial_id
    assert [item.status for item in registry.attempts()] == [
        AttemptStatus.FAILED,
        AttemptStatus.COMPLETED,
        AttemptStatus.COMPLETED,
    ]
    assert correction.supersedes_attempt_id == retry.attempt_id
    with pytest.raises(TypeError):
        correction.parameters["lookback"] = 40  # type: ignore[index]

    result = registry.to_result()
    assert result.metrics["attempt_count"] == 3
    assert result.metrics["trial_count"] == 1
    assert result.metrics["failed_attempts"] == 1
    assert {finding.state for finding in result.findings} == {
        FindingState.WARN,
        FindingState.UNKNOWN,
    }
    assert json.loads(result.to_json())["tables"]["attempts"][0]["status"] == "failed"


def test_registry_rejects_cross_trial_correction_and_duplicate_attempt_id() -> None:
    registry = ExperimentRegistry("momentum")
    original = registry.record(parameters={"lookback": 20}, metric=1.0, attempt_id="attempt_fixed")

    with pytest.raises(DataContractError, match="already exists"):
        registry.record(parameters={"lookback": 20}, metric=1.0, attempt_id="attempt_fixed")
    with pytest.raises(DataContractError, match="same trial"):
        registry.record(
            parameters={"lookback": 40},
            metric=1.1,
            supersedes_attempt_id=original.attempt_id,
            supersedes_reason="Not actually the same trial",
        )


def test_selection_preserves_complete_eligible_set() -> None:
    registry = ExperimentRegistry("momentum")
    first = registry.record(parameters={"lookback": 20}, metric=0.8)
    second = registry.record(parameters={"lookback": 40}, metric=1.2)
    third = registry.record(parameters={"lookback": 60}, metric=1.0)

    selection = registry.record_selection(
        eligible_trial_ids=[first.trial_id, second.trial_id, third.trial_id],
        selected_trial_ids=[second.trial_id],
        metric="sharpe",
        tie_breaking="lower_turnover_then_trial_id",
        exclusion_reasons={first.trial_id: "below threshold"},
    )

    assert selection.eligible_trial_ids == (first.trial_id, second.trial_id, third.trial_id)
    assert selection.selected_trial_ids == (second.trial_id,)
    assert registry.to_result().metrics["selection_count"] == 1

    with pytest.raises(MethodContractError, match="eligible set"):
        registry.record_selection(
            eligible_trial_ids=[first.trial_id],
            selected_trial_ids=[second.trial_id],
            metric="sharpe",
        )


def test_file_registry_reopens_and_rejects_metadata_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "experiments.sqlite3"
    with ExperimentRegistry("momentum", path=path, family="cross-sectional") as registry:
        recorded = registry.record(parameters={"lookback": 20}, metric=1.0)

    with ExperimentRegistry("momentum", path=path, family="cross-sectional") as reopened:
        assert reopened.attempts()[0].attempt_id == recorded.attempt_id

    with pytest.raises(DataContractError, match="metadata mismatch"):
        ExperimentRegistry("different-name", path=path, family="cross-sectional")


def test_concurrent_registries_cannot_reuse_attempt_identity(tmp_path: Path) -> None:
    path = tmp_path / "concurrent.sqlite3"
    first = ExperimentRegistry("momentum", path=path)
    second = ExperimentRegistry("momentum", path=path)

    def write(registry: ExperimentRegistry) -> str:
        try:
            registry.record(parameters={"lookback": 20}, metric=1.0, attempt_id="attempt_shared")
        except DataContractError:
            return "duplicate"
        return "recorded"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(write, [first, second]))
    first.close()
    second.close()

    assert sorted(outcomes) == ["duplicate", "recorded"]
    with ExperimentRegistry("momentum", path=path) as registry:
        assert len(registry.attempts()) == 1


def test_record_policy_validation_is_explicit() -> None:
    registry = ExperimentRegistry("momentum")

    with pytest.raises(MethodContractError, match="error_category"):
        registry.record(parameters={}, status="failed")
    with pytest.raises(MethodContractError, match="cannot record a metric"):
        registry.record(parameters={}, status="cancelled", metric=1.0)
    with pytest.raises(DataContractError, match="finite"):
        registry.record(parameters={}, metric=float("inf"))


def test_registry_close_is_idempotent() -> None:
    registry = ExperimentRegistry("close")
    registry.close()
    registry.close()
