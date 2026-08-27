from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parents[2] / ".github" / "scripts" / "compare_benchmarks.py"
PACKAGE_SCRIPT = Path(__file__).parents[2] / ".github" / "scripts" / "compare_package_metrics.py"


def _write(path: Path, *, median: float, checksum: str = "same") -> None:
    path.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "name": "legacy.case",
                        "median_seconds": median,
                        "checksum": checksum,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def test_benchmark_comparison_accepts_regressions_at_or_below_threshold(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    _write(baseline, median=1.0)
    _write(candidate, median=1.15)

    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(baseline), str(candidate)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0


def test_benchmark_comparison_blocks_slow_or_semantically_changed_cases(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    _write(baseline, median=1.0)
    _write(candidate, median=1.16, checksum="changed")

    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(baseline), str(candidate)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "correctness checksum changed" in result.stdout


def test_package_metric_comparison_records_wheel_and_import_evidence(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.whl"
    candidate = tmp_path / "candidate.whl"
    output = tmp_path / "package-regression.json"
    baseline.write_bytes(b"baseline")
    candidate.write_bytes(b"candidate")

    result = subprocess.run(
        [
            sys.executable,
            str(PACKAGE_SCRIPT),
            "--baseline-wheel",
            str(baseline),
            "--candidate-wheel",
            str(candidate),
            "--baseline-python",
            sys.executable,
            "--candidate-python",
            sys.executable,
            "--maximum-regression",
            "10",
            "--maximum-wheel-growth",
            "10",
            "--out",
            str(output),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema"] == "lacuna.package-regression"
    assert len(payload["baseline"]["cold_import_seconds"]) == 7
