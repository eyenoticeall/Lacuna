"""Run or validate Lacuna's private native-migration benchmark sidecar."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

from lacuna._migration_benchmark import (
    MigrationBenchmarkTarget,
    run_isolated_migration_benchmark,
    validate_artifact,
)
from lacuna.benchmark import benchmark_config_for_tier


def _source_commit() -> str:
    configured = os.environ.get("LACUNA_SOURCE_COMMIT") or os.environ.get("GITHUB_SHA")
    if configured:
        return configured
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    )
    if status.stdout.strip():
        raise RuntimeError(
            "native migration admission artifacts require a clean worktree and exact commit"
        )
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _dimensions(values: list[str]) -> dict[str, int | float | str | bool | None]:
    result: dict[str, int | float | str | bool | None] = {}
    for item in values:
        name, separator, raw_value = item.partition("=")
        if not separator or not name:
            raise ValueError("--dimension values must use NAME=VALUE")
        decoded = json.loads(raw_value)
        if not isinstance(decoded, str | int | float | bool) and decoded is not None:
            raise ValueError("dimension values must be JSON scalars")
        result[name] = decoded
    return result


def _write(path: Path, content: str, *, overwrite: bool) -> None:
    mode = "w" if overwrite else "x"
    with path.open(mode, encoding="utf-8", newline="\n") as stream:
        stream.write(content)
        stream.write("\n")


def _run(arguments: argparse.Namespace) -> int:
    config = benchmark_config_for_tier(
        arguments.tier,
        repetitions=arguments.repetitions,
        warmups=arguments.warmups,
        seed=arguments.seed,
    )
    target = MigrationBenchmarkTarget(
        candidate_id=arguments.candidate_id,
        public_operation=arguments.public_operation,
        reference_case=arguments.reference_case,
        candidate_case=arguments.candidate_case,
        effective_dimensions=_dimensions(arguments.dimension),
        public_latency_share=arguments.public_latency_share,
        public_rss_share=arguments.public_rss_share,
        asymptotic_or_unbounded=arguments.asymptotic_or_unbounded,
        bounded_memory_advantage=arguments.bounded_memory_advantage,
        absolute_tolerance=arguments.absolute_tolerance,
        relative_tolerance=arguments.relative_tolerance,
    )
    artifact = run_isolated_migration_benchmark(
        target,
        config,
        source_commit=_source_commit(),
        run_url=os.environ.get("GITHUB_SERVER_URL")
        and os.environ.get("GITHUB_REPOSITORY")
        and os.environ.get("GITHUB_RUN_ID")
        and (
            f"{os.environ['GITHUB_SERVER_URL']}/{os.environ['GITHUB_REPOSITORY']}"
            f"/actions/runs/{os.environ['GITHUB_RUN_ID']}"
        ),
    )
    validate_artifact(artifact.to_dict())
    content = artifact.to_json()
    if arguments.out is None:
        print(content)
    else:
        _write(arguments.out, content, overwrite=arguments.overwrite)
    return 0


def _validate(arguments: argparse.Namespace) -> int:
    decoded = json.loads(arguments.path.read_text(encoding="utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError("migration benchmark artifact must be a JSON object")
    validate_artifact(decoded)
    if arguments.require_state is not None:
        admission = decoded.get("admission")
        if not isinstance(admission, dict) or admission.get("state") != arguments.require_state:
            raise ValueError(f"migration benchmark state must be {arguments.require_state!r}")
    if arguments.source_commit is not None and decoded.get("source_commit") != (
        arguments.source_commit
    ):
        raise ValueError("migration benchmark source commit does not match")
    if arguments.candidate_id is not None:
        target = decoded.get("target")
        if not isinstance(target, dict) or target.get("candidate_id") != arguments.candidate_id:
            raise ValueError("migration benchmark candidate ID does not match")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run")
    run.add_argument("--candidate-id", required=True)
    run.add_argument("--public-operation", required=True)
    run.add_argument("--reference-case", required=True)
    run.add_argument("--candidate-case")
    run.add_argument("--tier", choices=("smoke", "small", "medium"), default="medium")
    run.add_argument("--repetitions", type=int, default=7)
    run.add_argument("--warmups", type=int, default=2)
    run.add_argument("--seed", type=int, default=42)
    run.add_argument("--dimension", action="append", default=[])
    run.add_argument("--public-latency-share", type=float)
    run.add_argument("--public-rss-share", type=float)
    run.add_argument("--asymptotic-or-unbounded", action="store_true")
    run.add_argument("--bounded-memory-advantage", action="store_true")
    run.add_argument("--absolute-tolerance", type=float, default=0.0)
    run.add_argument("--relative-tolerance", type=float, default=0.0)
    run.add_argument("--out", type=Path)
    run.add_argument("--overwrite", action="store_true")

    validate = subparsers.add_parser("validate")
    validate.add_argument("path", type=Path)
    validate.add_argument(
        "--require-state",
        choices=(
            "PROPOSED",
            "MEASURED",
            "ADMITTED",
            "SHIPPED_NATIVE",
            "OPTIMIZED_NON_NATIVE",
            "NOT_MIGRATING",
            "BLOCKED",
        ),
    )
    validate.add_argument("--source-commit")
    validate.add_argument("--candidate-id")

    arguments = parser.parse_args()
    return _run(arguments) if arguments.command == "run" else _validate(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
