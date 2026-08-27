from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]
VERIFIER = ROOT / ".github/scripts/verify_release.py"
RUSTSEC_INSTALL = "cargo install cargo-audit --locked --version 0.22.2"
RUSTSEC_AUDIT = "cargo audit --deny warnings --file Cargo.lock"


def test_release_source_contract_accepts_the_declared_release() -> None:
    subprocess.run(
        [sys.executable, str(VERIFIER), "source", "--tag", "v0.14.0"],
        cwd=ROOT,
        check=True,
    )


def test_release_source_contract_rejects_a_mismatched_tag() -> None:
    result = subprocess.run(
        [sys.executable, str(VERIFIER), "source", "--tag", "v0.14.1"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "does not match expected release tag" in result.stderr


def test_ci_and_release_rehearsal_pin_the_strict_rustsec_audit() -> None:
    for workflow_name in ("ci.yml", "release.yml"):
        workflow = (ROOT / ".github/workflows" / workflow_name).read_text(encoding="utf-8")
        assert RUSTSEC_INSTALL in workflow
        assert RUSTSEC_AUDIT in workflow
