from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parents[2] / ".github" / "scripts" / "compare_benchmarks.py"


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
