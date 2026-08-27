"""Create and verify Lacuna's exact-source non-publishing release preflight."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn

SCHEMA = "lacuna.release-preflight"
VERSION = 1
LEDGER = Path("docs/development/rust-migration-decisions.md")
TERMINAL_STATES = {
    "BLOCKED",
    "NOT_MIGRATING",
    "OPTIMIZED_NON_NATIVE",
    "SHIPPED_NATIVE",
}
ALL_STATES = TERMINAL_STATES | {"ADMITTED", "MEASURED", "PROPOSED"}
FOUNDATION_IDS = ("F-01", "F-02a", "F-02b", "F-03a", "F-03b", "F-04", "F-05")
CANDIDATE_IDS = tuple(f"R-{number:02d}" for number in range(1, 17))
EXPECTED_IDS = FOUNDATION_IDS + CANDIDATE_IDS
EXPECTED_NATIVE_CANDIDATES = ("R-01", "R-08")
REQUIRED_GATES = {
    "artifact_validation",
    "ci",
    "native_admission",
    "options_compatibility",
    "release_rehearsal",
    "same_wheel_abi",
    "source_distribution",
    "statistical_calibration",
    "target_wheels",
}


def fail(message: str) -> NoReturn:
    raise RuntimeError(message)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _source_versions(root: Path) -> tuple[str, str]:
    core = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    options = tomllib.loads(
        (root / "extensions/lacuna-options/pyproject.toml").read_text(encoding="utf-8")
    )
    return core["project"]["version"], options["project"]["version"]


def _head(root: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def read_decisions(root: Path) -> dict[str, str]:
    """Read the reviewed Markdown ledger into a stable decision mapping."""

    decisions: dict[str, str] = {}
    for line in (root / LEDGER).read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        identifier_match = re.match(r"(?P<identifier>[FR]-\d{2}(?:[ab])?)\b", cells[0])
        if identifier_match is None or cells[1] not in ALL_STATES:
            continue
        identifier = identifier_match.group("identifier")
        if identifier in decisions:
            fail(f"migration ledger repeats decision {identifier}")
        decisions[identifier] = cells[1]
    missing = sorted(set(EXPECTED_IDS).difference(decisions))
    unexpected = sorted(set(decisions).difference(EXPECTED_IDS))
    if missing or unexpected:
        fail(f"migration ledger IDs disagree: missing={missing}, unexpected={unexpected}")
    return {identifier: decisions[identifier] for identifier in EXPECTED_IDS}


def require_terminal_decisions(decisions: dict[str, str]) -> None:
    provisional = {
        identifier: state for identifier, state in decisions.items() if state not in TERMINAL_STATES
    }
    if provisional:
        fail(f"migration ledger contains non-terminal decisions: {provisional}")
    for candidate in EXPECTED_NATIVE_CANDIDATES:
        if decisions[candidate] != "SHIPPED_NATIVE":
            fail(f"{candidate} must be SHIPPED_NATIVE in a release preflight")
    if decisions["F-01"] != "SHIPPED_NATIVE":
        fail("F-01 must be SHIPPED_NATIVE after the same-wheel ABI gate")


def _gate_mapping(values: list[str]) -> dict[str, str]:
    gates: dict[str, str] = {}
    for value in values:
        name, separator, state = value.partition("=")
        if not separator or not name or state not in {"success", "failure"}:
            fail("--gate values must use NAME=success or NAME=failure")
        if name in gates:
            fail(f"gate {name!r} was supplied more than once")
        gates[name] = state
    missing = sorted(REQUIRED_GATES.difference(gates))
    unexpected = sorted(set(gates).difference(REQUIRED_GATES))
    failed = sorted(name for name, state in gates.items() if state != "success")
    if missing or unexpected or failed:
        fail(
            "preflight gates are incomplete: "
            f"missing={missing}, unexpected={unexpected}, failed={failed}"
        )
    return {name: gates[name] for name in sorted(gates)}


def _native_benchmarks(directory: Path, *, source_commit: str) -> list[dict[str, object]]:
    results: dict[str, dict[str, object]] = {}
    for path in sorted(directory.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema") != "lacuna.native-migration-benchmark":
            fail(f"{path.name} is not a native-migration benchmark")
        if payload.get("version") != 1 or payload.get("source_commit") != source_commit:
            fail(f"{path.name} does not describe the exact preflight source")
        target = payload.get("target")
        admission = payload.get("admission")
        config = payload.get("config")
        if not isinstance(target, dict) or not isinstance(admission, dict):
            fail(f"{path.name} has malformed target or admission evidence")
        if not isinstance(config, dict):
            fail(f"{path.name} has malformed benchmark configuration")
        candidate_id = target.get("candidate_id")
        if candidate_id not in EXPECTED_NATIVE_CANDIDATES:
            fail(f"{path.name} has unexpected native candidate {candidate_id!r}")
        if candidate_id in results:
            fail(f"native benchmark evidence repeats {candidate_id}")
        if admission.get("state") != "ADMITTED":
            fail(f"{candidate_id} did not reproduce its native admission gate")
        if admission.get("correctness_match") is not True:
            fail(f"{candidate_id} native benchmark failed correctness comparison")
        if config.get("warmups") != 2 or config.get("repetitions") != 7:
            fail(f"{candidate_id} did not use the release benchmark protocol")
        results[candidate_id] = {
            "candidate_id": candidate_id,
            "file": path.name,
            "sha256": _sha256(path),
            "size_bytes": path.stat().st_size,
        }
    missing = sorted(set(EXPECTED_NATIVE_CANDIDATES).difference(results))
    if missing:
        fail(f"native preflight evidence is missing candidates: {missing}")
    return [results[candidate] for candidate in EXPECTED_NATIVE_CANDIDATES]


def _artifact_hashes(directory: Path) -> list[dict[str, object]]:
    paths = sorted(path for path in directory.iterdir() if path.is_file())
    if not paths:
        fail("preflight distribution directory is empty")
    return [
        {"file": path.name, "sha256": _sha256(path), "size_bytes": path.stat().st_size}
        for path in paths
    ]


def create_manifest(arguments: argparse.Namespace) -> dict[str, object]:
    root = arguments.root.resolve()
    source_commit = arguments.source_commit.lower()
    if re.fullmatch(r"[0-9a-f]{40}", source_commit) is None:
        fail("source commit must be a full 40-character hexadecimal SHA")
    if _head(root) != source_commit:
        fail("checked-out HEAD does not match the requested preflight source")
    core_version, options_version = _source_versions(root)
    if core_version != arguments.core_version or options_version != arguments.options_version:
        fail(
            "preflight version inputs disagree with source: "
            f"core={core_version}, options={options_version}"
        )
    decisions = read_decisions(root)
    require_terminal_decisions(decisions)
    gates = _gate_mapping(arguments.gate)
    manifest = {
        "schema": SCHEMA,
        "version": VERSION,
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "source_commit": source_commit,
        "core_version": core_version,
        "options_version": options_version,
        "workflow_run_url": arguments.run_url,
        "gates": gates,
        "candidate_decisions": decisions,
        "native_benchmarks": _native_benchmarks(
            arguments.native_benchmarks.resolve(), source_commit=source_commit
        ),
        "artifacts": _artifact_hashes(arguments.dist.resolve()),
        "status": "verified",
    }
    json.dumps(manifest, allow_nan=False, sort_keys=True)
    return manifest


def verify_manifest(
    root: Path,
    path: Path,
    *,
    source_commit: str,
    core_version: str,
    options_version: str,
) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        fail("release preflight manifest must be an object")
    expected_scalars = {
        "schema": SCHEMA,
        "version": VERSION,
        "source_commit": source_commit.lower(),
        "core_version": core_version,
        "options_version": options_version,
        "status": "verified",
    }
    for name, expected in expected_scalars.items():
        if payload.get(name) != expected:
            fail(f"preflight {name} is {payload.get(name)!r}, expected {expected!r}")
    source_core, source_options = _source_versions(root)
    if (source_core, source_options) != (core_version, options_version):
        fail("preflight versions do not match the checked-out source")
    decisions = read_decisions(root)
    require_terminal_decisions(decisions)
    if payload.get("candidate_decisions") != decisions:
        fail("preflight candidate decisions do not match the checked-out ledger")
    gates = payload.get("gates")
    if not isinstance(gates, dict):
        fail("preflight gates must be an object")
    _gate_mapping([f"{name}={state}" for name, state in gates.items()])
    native_benchmarks = payload.get("native_benchmarks")
    if not isinstance(native_benchmarks, list):
        fail("preflight native benchmark manifest must be a list")
    benchmark_ids = {
        item.get("candidate_id") for item in native_benchmarks if isinstance(item, dict)
    }
    if benchmark_ids != set(EXPECTED_NATIVE_CANDIDATES):
        fail("preflight native benchmark set is incomplete")
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        fail("preflight artifact manifest is empty")
    for item in [*native_benchmarks, *artifacts]:
        if (
            not isinstance(item, dict)
            or re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256"))) is None
            or not isinstance(item.get("size_bytes"), int)
            or item["size_bytes"] <= 0
        ):
            fail("preflight contains an invalid artifact checksum record")
    json.dumps(payload, allow_nan=False, sort_keys=True)
    return payload


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("--root", type=Path, default=Path.cwd())
    commands = root.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("--source-commit", required=True)
    create.add_argument("--core-version", required=True)
    create.add_argument("--options-version", required=True)
    create.add_argument("--dist", type=Path, required=True)
    create.add_argument("--native-benchmarks", type=Path, required=True)
    create.add_argument("--run-url", required=True)
    create.add_argument("--gate", action="append", default=[])
    create.add_argument("--out", type=Path, required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--source-commit", required=True)
    verify.add_argument("--core-version", required=True)
    verify.add_argument("--options-version", required=True)
    ledger = commands.add_parser("ledger")
    ledger.add_argument("--require-terminal", action="store_true")
    return root


def main() -> None:
    arguments = parser().parse_args()
    root = arguments.root.resolve()
    if arguments.command == "create":
        manifest = create_manifest(arguments)
        arguments.out.write_text(
            json.dumps(manifest, allow_nan=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print(json.dumps({"manifest": str(arguments.out), "status": "verified"}))
    elif arguments.command == "verify":
        verify_manifest(
            root,
            arguments.manifest,
            source_commit=arguments.source_commit,
            core_version=arguments.core_version,
            options_version=arguments.options_version,
        )
        print(json.dumps({"manifest": str(arguments.manifest), "status": "verified"}))
    else:
        decisions = read_decisions(root)
        if arguments.require_terminal:
            require_terminal_decisions(decisions)
        print(json.dumps(decisions, sort_keys=True))


if __name__ == "__main__":
    main()
