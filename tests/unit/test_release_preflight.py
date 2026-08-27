from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / ".github/scripts/release_preflight.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("lacuna_release_preflight", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


PREFLIGHT = _load_script()


def _root(tmp_path: Path, *, provisional: str | None = None) -> tuple[Path, dict[str, str]]:
    root = tmp_path / "source"
    ledger = root / "docs/development/rust-migration-decisions.md"
    ledger.parent.mkdir(parents=True)
    decisions = {
        identifier: "SHIPPED_NATIVE"
        if identifier in {"F-01", "R-01", "R-08"}
        else "OPTIMIZED_NON_NATIVE"
        for identifier in PREFLIGHT.EXPECTED_IDS
    }
    if provisional is not None:
        decisions[provisional] = "ADMITTED"
    ledger.write_text(
        "# Ledger\n\n"
        + "\n".join(
            f"| {identifier} test | {state} | evidence |" for identifier, state in decisions.items()
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "pyproject.toml").write_text(
        '[project]\nname = "lacuna-quant"\nversion = "0.14.0"\n', encoding="utf-8"
    )
    options = root / "extensions/lacuna-options"
    options.mkdir(parents=True)
    (options / "pyproject.toml").write_text(
        '[project]\nname = "lacuna-options"\nversion = "0.2.1"\n', encoding="utf-8"
    )
    return root, decisions


def _manifest(decisions: dict[str, str], source_commit: str) -> dict[str, object]:
    checksum = "a" * 64
    return {
        "schema": PREFLIGHT.SCHEMA,
        "version": PREFLIGHT.VERSION,
        "source_commit": source_commit,
        "core_version": "0.14.0",
        "options_version": "0.2.1",
        "status": "verified",
        "gates": {name: "success" for name in PREFLIGHT.REQUIRED_GATES},
        "candidate_decisions": decisions,
        "native_benchmarks": [
            {
                "candidate_id": candidate,
                "file": f"{candidate}.json",
                "sha256": checksum,
                "size_bytes": 100,
            }
            for candidate in PREFLIGHT.EXPECTED_NATIVE_CANDIDATES
        ],
        "artifacts": [{"file": "lacuna_quant.whl", "sha256": checksum, "size_bytes": 200}],
    }


def test_release_preflight_reads_every_reviewed_decision(tmp_path: Path) -> None:
    root, expected = _root(tmp_path)
    decisions = PREFLIGHT.read_decisions(root)
    assert decisions == expected
    PREFLIGHT.require_terminal_decisions(decisions)


def test_release_preflight_rejects_provisional_native_decision(tmp_path: Path) -> None:
    root, _ = _root(tmp_path, provisional="R-08")
    with pytest.raises(RuntimeError, match="non-terminal"):
        PREFLIGHT.require_terminal_decisions(PREFLIGHT.read_decisions(root))


def test_release_preflight_manifest_is_bound_to_source_and_ledger(tmp_path: Path) -> None:
    root, decisions = _root(tmp_path)
    source_commit = "1" * 40
    manifest = tmp_path / "release-preflight.json"
    manifest.write_text(json.dumps(_manifest(decisions, source_commit)), encoding="utf-8")

    payload = PREFLIGHT.verify_manifest(
        root,
        manifest,
        source_commit=source_commit,
        core_version="0.14.0",
        options_version="0.2.1",
    )
    assert payload["status"] == "verified"

    decisions["R-02"] = "ADMITTED"
    manifest.write_text(json.dumps(_manifest(decisions, source_commit)), encoding="utf-8")
    with pytest.raises(RuntimeError, match="candidate decisions"):
        PREFLIGHT.verify_manifest(
            root,
            manifest,
            source_commit=source_commit,
            core_version="0.14.0",
            options_version="0.2.1",
        )
