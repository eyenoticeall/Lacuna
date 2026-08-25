from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]
VERIFIER = ROOT / ".github/scripts/verify_release.py"


def test_release_source_contract_accepts_the_declared_release() -> None:
    subprocess.run(
        [sys.executable, str(VERIFIER), "source", "--tag", "v0.3.0"],
        cwd=ROOT,
        check=True,
    )


def test_release_source_contract_rejects_a_mismatched_tag() -> None:
    result = subprocess.run(
        [sys.executable, str(VERIFIER), "source", "--tag", "v0.3.1"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "does not match expected release tag" in result.stderr
