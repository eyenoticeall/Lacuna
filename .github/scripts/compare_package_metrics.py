"""Compare stable wheel size and cold import latency on one pinned runner."""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import time
from pathlib import Path


def _cold_imports(interpreter: Path, *, warmups: int = 2, repetitions: int = 7) -> list[float]:
    command = [
        str(interpreter),
        "-c",
        "import lacuna; assert lacuna.__version__",
    ]
    for _ in range(warmups):
        subprocess.run(command, check=True, capture_output=True)
    timings = []
    for _ in range(repetitions):
        started = time.perf_counter()
        subprocess.run(command, check=True, capture_output=True)
        timings.append(time.perf_counter() - started)
    return timings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-wheel", type=Path, required=True)
    parser.add_argument("--candidate-wheel", type=Path, required=True)
    parser.add_argument("--baseline-python", type=Path, required=True)
    parser.add_argument("--candidate-python", type=Path, required=True)
    parser.add_argument("--maximum-regression", type=float, default=0.15)
    parser.add_argument("--maximum-wheel-growth", type=float, default=0.20)
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()

    baseline_timings = _cold_imports(arguments.baseline_python)
    candidate_timings = _cold_imports(arguments.candidate_python)
    baseline_median = statistics.median(baseline_timings)
    candidate_median = statistics.median(candidate_timings)
    latency_regression = candidate_median / baseline_median - 1.0
    baseline_size = arguments.baseline_wheel.stat().st_size
    candidate_size = arguments.candidate_wheel.stat().st_size
    wheel_growth = candidate_size / baseline_size - 1.0
    payload = {
        "schema": "lacuna.package-regression",
        "version": 1,
        "baseline": {
            "wheel": arguments.baseline_wheel.name,
            "wheel_bytes": baseline_size,
            "cold_import_seconds": baseline_timings,
            "median_cold_import_seconds": baseline_median,
        },
        "candidate": {
            "wheel": arguments.candidate_wheel.name,
            "wheel_bytes": candidate_size,
            "cold_import_seconds": candidate_timings,
            "median_cold_import_seconds": candidate_median,
        },
        "latency_regression_fraction": latency_regression,
        "wheel_growth_fraction": wheel_growth,
        "maximum_latency_regression_fraction": arguments.maximum_regression,
        "maximum_wheel_growth_fraction": arguments.maximum_wheel_growth,
    }
    arguments.out.write_text(
        json.dumps(payload, allow_nan=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    failures = []
    if latency_regression > arguments.maximum_regression:
        failures.append(
            f"cold import regression {latency_regression:.1%} exceeds "
            f"{arguments.maximum_regression:.1%}"
        )
    if wheel_growth > arguments.maximum_wheel_growth:
        failures.append(
            f"wheel growth {wheel_growth:.1%} exceeds {arguments.maximum_wheel_growth:.1%}"
        )
    if failures:
        print("; ".join(failures))
        return 1
    print(json.dumps(payload, allow_nan=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
