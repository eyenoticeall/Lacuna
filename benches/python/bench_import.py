"""Minimal import benchmark used to catch accidental startup regressions."""

from __future__ import annotations

import subprocess
import sys
import time


def main(repetitions: int = 10) -> None:
    timings: list[float] = []
    for _ in range(repetitions):
        started = time.perf_counter()
        subprocess.run(
            [sys.executable, "-c", "import lacuna"],
            check=True,
            capture_output=True,
        )
        timings.append(time.perf_counter() - started)
    print(f"lacuna import median ({repetitions} runs): {sorted(timings)[repetitions // 2]:.4f}s")


if __name__ == "__main__":
    main()
