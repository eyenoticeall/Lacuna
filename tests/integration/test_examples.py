from __future__ import annotations

import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]


@pytest.mark.parametrize(
    "example",
    ["foundation.py", "factor_research.py", "purged_cv.py"],
)
def test_documented_examples_execute(example: str, capsys: object) -> None:
    runpy.run_path(str(ROOT / "examples" / example), run_name="__main__")
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert captured.out.strip()
