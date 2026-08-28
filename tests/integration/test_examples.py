from __future__ import annotations

import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]


@pytest.mark.parametrize(
    "example",
    [
        "foundation.py",
        "quickstart.py",
        "factor_research.py",
        "purged_cv.py",
        "standard_audit.py",
    ],
)
def test_documented_examples_execute(
    example: str,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    runpy.run_path(str(ROOT / "examples" / example), run_name="__main__")
    captured = capsys.readouterr()
    assert captured.out.strip()
    if example == "quickstart.py":
        assert (tmp_path / "lacuna-audit.html").is_file()
