from __future__ import annotations

import json

import numpy as np
import polars as pl

from lacuna.cli import main


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
