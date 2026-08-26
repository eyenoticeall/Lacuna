from __future__ import annotations

import json

import numpy as np
import polars as pl
import pytest

import lacuna.cli as cli
from lacuna.cli import main
from lacuna.types import AnalysisResult, ResultMetadata


def test_doctor_has_machine_readable_output(capsys: object) -> None:
    assert main(["doctor", "--json"]) == 0
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    payload = json.loads(captured.out)
    assert "lacuna_version" in payload
    assert "native" in payload


def _write_signal_inputs(root: object) -> tuple[str, str]:
    directory = root  # type: ignore[assignment]
    periods = 14
    instruments = 6
    names = [f"asset-{index}" for index in range(instruments)]
    signal = pl.DataFrame(
        {
            "time": np.repeat(np.arange(periods - 2), instruments),
            "instrument": np.tile(names, periods - 2),
            "signal": np.tile(np.arange(instruments, dtype=np.float64), periods - 2),
        }
    )
    prices = pl.DataFrame(
        {
            "time": np.tile(np.arange(periods), instruments),
            "instrument": np.repeat(names, periods),
            "close": [
                100.0 * (1.0 + 0.002 * (index + 1)) ** time
                for index in range(instruments)
                for time in range(periods)
            ],
        }
    )
    signal_path = directory / "signal.parquet"
    price_path = directory / "prices.parquet"
    signal.write_parquet(signal_path)
    prices.write_parquet(price_path)
    return str(signal_path), str(price_path)


def test_signal_command_emits_clean_machine_json(tmp_path: object, capsys: object) -> None:
    signal_path, price_path = _write_signal_inputs(tmp_path)
    exit_code = main(
        [
            "signal",
            "--signal",
            signal_path,
            "--prices",
            price_path,
            "--horizon",
            "1D",
            "--horizon",
            "2D",
            "--quantiles",
            "3",
            "--bootstrap-resamples",
            "100",
            "--seed",
            "9",
            "--no-native",
            "--format",
            "json",
        ]
    )
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["metadata"]["method"] == "audit.v0_1"
    assert captured.err == ""
    assert "\x1b[" not in captured.out


def test_signal_command_writes_without_silent_overwrite(tmp_path: object, capsys: object) -> None:
    signal_path, price_path = _write_signal_inputs(tmp_path)
    destination = tmp_path / "report.md"  # type: ignore[operator]
    arguments = [
        "signal",
        "--signal",
        signal_path,
        "--prices",
        price_path,
        "--horizon",
        "1D",
        "--quantiles",
        "3",
        "--bootstrap-resamples",
        "100",
        "--no-native",
        "--out",
        str(destination),
    ]

    assert main(arguments) == 0
    first = capsys.readouterr()  # type: ignore[attr-defined]
    assert first.out == ""
    assert "wrote Lacuna audit" in first.err
    assert destination.read_text(encoding="utf-8").startswith("# Lacuna audit")

    assert main(arguments) == 1
    second = capsys.readouterr()  # type: ignore[attr-defined]
    assert "refusing to overwrite" in second.err


def test_signal_command_writes_and_cli_verifies_bundle(tmp_path: object, capsys: object) -> None:
    signal_path, price_path = _write_signal_inputs(tmp_path)
    bundle_path = tmp_path / "study.lacuna"  # type: ignore[operator]
    report_path = tmp_path / "report.json"  # type: ignore[operator]

    assert (
        main(
            [
                "signal",
                "--signal",
                signal_path,
                "--prices",
                price_path,
                "--horizon",
                "1D",
                "--quantiles",
                "3",
                "--bootstrap-resamples",
                "100",
                "--seed",
                "9",
                "--no-native",
                "--out",
                str(report_path),
                "--bundle",
                str(bundle_path),
            ]
        )
        == 0
    )
    created = capsys.readouterr()  # type: ignore[attr-defined]
    assert created.out == ""
    assert "wrote Lacuna reproducibility bundle" in created.err

    assert main(["bundle", "verify", str(bundle_path), "--json"]) == 0
    verified = capsys.readouterr()  # type: ignore[attr-defined]
    payload = json.loads(verified.out)
    assert payload["integrity_verified"] is True
    assert payload["authenticity_verified"] is False
    assert payload["artifact_count"] == 5
    assert verified.err == ""


def test_signal_command_rejects_unsupported_input_format(tmp_path: object, capsys: object) -> None:
    invalid = tmp_path / "signal.txt"  # type: ignore[operator]
    exit_code = main(
        [
            "signal",
            "--signal",
            str(invalid),
            "--prices",
            str(invalid),
        ]
    )
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert exit_code == 1
    assert "unsupported input format" in captured.err


def test_standard_audit_command_loads_named_result_json(tmp_path: object, capsys: object) -> None:
    directory = tmp_path  # type: ignore[assignment]
    split_path = directory / "split.json"
    split_path.write_text(
        AnalysisResult(metadata=ResultMetadata(method="cv.purged_kfold")).to_json(),
        encoding="utf-8",
    )

    assert (
        main(
            [
                "audit",
                "--scope",
                "strategy",
                "--evidence",
                f"split={split_path}",
                "--format",
                "json",
            ]
        )
        == 0
    )
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    payload = json.loads(captured.out)
    assert payload["metadata"]["method"] == "audit.standard"
    assert payload["metrics"]["recognized_result_count"] == 1
    assert payload["metrics"]["required_evidence_coverage"] > 0.0
    assert "robustness_score" not in payload["metrics"]
    assert captured.err == ""


def test_standard_audit_command_bundles_named_evidence(tmp_path: object, capsys: object) -> None:
    directory = tmp_path  # type: ignore[assignment]
    evidence_path = directory / "adapter.json"
    evidence_path.write_text(
        AnalysisResult(metadata=ResultMetadata(method="adapters.vendor_schema")).to_json(),
        encoding="utf-8",
    )
    bundle_path = directory / "standard.lacuna"

    assert (
        main(
            [
                "audit",
                "--scope",
                "strategy",
                "--evidence",
                f"vendor={evidence_path}",
                "--bundle",
                str(bundle_path),
                "--format",
                "json",
            ]
        )
        == 0
    )
    created = capsys.readouterr()  # type: ignore[attr-defined]
    assert "wrote Lacuna reproducibility bundle" in created.err

    assert main(["bundle", "verify", str(bundle_path), "--json"]) == 0
    verified = capsys.readouterr()  # type: ignore[attr-defined]
    payload = json.loads(verified.out)
    assert payload["integrity_verified"] is True
    assert payload["artifact_count"] == 7


def test_standard_audit_command_rejects_duplicate_or_invalid_evidence(
    tmp_path: object,
    capsys: object,
) -> None:
    directory = tmp_path  # type: ignore[assignment]
    valid = directory / "valid.json"
    valid.write_text(
        AnalysisResult(metadata=ResultMetadata(method="cv.purged_kfold")).to_json(),
        encoding="utf-8",
    )
    assert (
        main(
            [
                "audit",
                "--evidence",
                f"same={valid}",
                "--evidence",
                f"same={valid}",
            ]
        )
        == 1
    )
    duplicate = capsys.readouterr()  # type: ignore[attr-defined]
    assert "duplicate evidence name" in duplicate.err

    invalid = directory / "invalid.json"
    invalid.write_text('{"value": NaN}', encoding="utf-8")
    assert main(["audit", "--evidence", f"invalid={invalid}"]) == 1
    rejected = capsys.readouterr()  # type: ignore[attr-defined]
    assert "non-finite constant" in rejected.err
    assert "NaN" not in rejected.out


def test_standard_audit_command_fail_on_warn_uses_audit_exit_code(
    tmp_path: object,
    capsys: object,
) -> None:
    directory = tmp_path  # type: ignore[assignment]
    evidence_path = directory / "unknown.json"
    evidence_path.write_text(
        AnalysisResult(metadata=ResultMetadata(method="future.method")).to_json(),
        encoding="utf-8",
    )
    assert (
        main(
            [
                "audit",
                "--evidence",
                f"unknown={evidence_path}",
                "--fail-on",
                "warn",
                "--format",
                "json",
            ]
        )
        == 3
    )
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert json.loads(captured.out)["metrics"]["unrecognized_result_count"] == 1


def test_audit_commands_reject_identical_report_and_bundle_paths(
    tmp_path: object,
    capsys: object,
) -> None:
    destination = tmp_path / "same-output"  # type: ignore[operator]
    assert (
        main(
            [
                "audit",
                "--out",
                str(destination),
                "--bundle",
                str(destination),
            ]
        )
        == 1
    )
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert "must use different paths" in captured.err
    assert not destination.exists()


def test_standard_audit_command_bounds_reads_and_uses_bundle_safe_names(
    tmp_path: object,
    capsys: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    oversized = tmp_path / "oversized.json"  # type: ignore[operator]
    oversized.write_bytes(b"123456789")
    monkeypatch.setattr(cli, "_MAX_EVIDENCE_BYTES", 8)
    assert main(["audit", "--evidence", f"oversized={oversized}"]) == 1
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert "exceeds the 8-byte limit" in captured.err

    with pytest.raises(SystemExit) as raised:
        main(["audit", "--evidence", f"Bad.Name={oversized}"])
    assert raised.value.code == 2
    invalid_name = capsys.readouterr()  # type: ignore[attr-defined]
    assert "must match [a-z][a-z0-9_-]{0,63}" in invalid_name.err


def test_bench_command_emits_versioned_json(capsys: object) -> None:
    exit_code = main(
        [
            "bench",
            "--tier",
            "smoke",
            "--repetitions",
            "1",
            "--warmups",
            "0",
            "--no-native",
        ]
    )
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["schema_version"] == "1"
    assert payload["benchmark_version"] == 4
    assert captured.err == ""
