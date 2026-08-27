#!/usr/bin/env python3
"""Fail when a same-runner candidate has an unexplained legacy regression."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import cast


def _cases(path: Path) -> dict[str, dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list):
        raise ValueError(f"{path} does not contain benchmark cases")
    cases: dict[str, dict[str, object]] = {}
    for raw in raw_cases:
        if not isinstance(raw, dict) or not isinstance(raw.get("name"), str):
            raise ValueError(f"{path} contains an invalid benchmark case")
        name = cast(str, raw["name"])
        if name in cases:
            raise ValueError(f"{path} contains duplicate case {name!r}")
        cases[name] = raw
    return cases


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--maximum-regression", type=float, default=0.15)
    parser.add_argument("--minimum-absolute-regression", type=float, default=0.001)
    arguments = parser.parse_args()
    if not 0.0 <= arguments.maximum_regression < 1.0:
        parser.error("--maximum-regression must be in [0, 1)")
    if (
        not math.isfinite(arguments.minimum_absolute_regression)
        or arguments.minimum_absolute_regression < 0.0
    ):
        parser.error("--minimum-absolute-regression must be finite and non-negative")

    baseline = _cases(arguments.baseline)
    candidate = _cases(arguments.candidate)
    failures: list[str] = []
    rows: list[tuple[str, float, float, float, float]] = []
    for name, reference in sorted(baseline.items()):
        if name not in candidate:
            failures.append(f"candidate is missing legacy benchmark {name}")
            continue
        observed = candidate[name]
        if reference.get("checksum") != observed.get("checksum"):
            failures.append(f"{name}: correctness checksum changed")
            continue
        baseline_seconds = reference.get("median_seconds")
        candidate_seconds = observed.get("median_seconds")
        if not isinstance(baseline_seconds, int | float) or not isinstance(
            candidate_seconds, int | float
        ):
            failures.append(f"{name}: median timing is not numeric")
            continue
        baseline_value = float(baseline_seconds)
        candidate_value = float(candidate_seconds)
        if not math.isfinite(baseline_value) or baseline_value <= 0.0:
            failures.append(f"{name}: baseline median must be finite and positive")
            continue
        if not math.isfinite(candidate_value) or candidate_value <= 0.0:
            failures.append(f"{name}: candidate median must be finite and positive")
            continue
        absolute_regression = candidate_value - baseline_value
        regression = candidate_value / baseline_value - 1.0
        rows.append((name, baseline_value, candidate_value, absolute_regression, regression))
        if (
            regression > arguments.maximum_regression
            and absolute_regression > arguments.minimum_absolute_regression
        ):
            failures.append(
                f"{name}: median regressed {regression:.1%}, above "
                f"{arguments.maximum_regression:.1%}, and added "
                f"{absolute_regression:.6g}s, above the "
                f"{arguments.minimum_absolute_regression:.6g}s noise floor"
            )

    print("case\tbaseline_s\tcandidate_s\tabsolute_delta_s\trelative_delta")
    for name, baseline_value, candidate_value, absolute_regression, regression in rows:
        print(
            f"{name}\t{baseline_value:.6g}\t{candidate_value:.6g}\t"
            f"{absolute_regression:+.6g}\t{regression:+.1%}"
        )
    if failures:
        print("benchmark comparison failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
