from __future__ import annotations

import ast
import inspect
import re
from collections.abc import Iterator
from pathlib import Path

import pytest

import lacuna

ROOT = Path(__file__).parents[2]
CURRENT_DOCUMENTS = (
    ROOT / "README.md",
    *sorted((ROOT / "docs").rglob("*.md")),
)
DOCUMENTS = (ROOT / "LACUNA_TECHNICAL_SPEC.md", *CURRENT_DOCUMENTS)
PYTHON_FENCE = re.compile(
    r"^```(?:python|py)\s*$\n(.*?)^```\s*$",
    re.MULTILINE | re.DOTALL,
)
STALE_EXTRA = re.compile(r"(?<!lacuna-quant)lacuna\[(?:statistics|report|pandas|duckdb|ml|all)\]")


def _python_blocks(paths: tuple[Path, ...]) -> Iterator[tuple[Path, int, str]]:
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for index, match in enumerate(PYTHON_FENCE.finditer(text), start=1):
            yield path, index, match.group(1)


def _root_lacuna_callable(call: ast.Call) -> tuple[bool, object | None]:
    attributes: list[str] = []
    current = call.func
    while isinstance(current, ast.Attribute):
        attributes.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name) or current.id not in {"lacuna", "lc"}:
        return False, None

    value: object = lacuna
    for attribute in reversed(attributes):
        try:
            value = getattr(value, attribute)
        except AttributeError:
            return True, None
    return True, value


def test_documented_python_blocks_parse() -> None:
    issues: list[str] = []
    for path, block_index, source in _python_blocks(DOCUMENTS):
        try:
            ast.parse(source)
        except SyntaxError as error:
            issues.append(f"{path}:{block_index}:{error.lineno}: {error.msg}")

    assert not issues, "\n".join(issues)


def test_current_python_examples_match_root_signatures() -> None:
    issues: list[str] = []
    for path, block_index, source in _python_blocks(CURRENT_DOCUMENTS):
        tree = ast.parse(source)

        for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
            is_root_call, value = _root_lacuna_callable(call)
            if not is_root_call or any(keyword.arg is None for keyword in call.keywords):
                continue
            name = ast.unparse(call.func)
            if value is None:
                issues.append(f"{path}:{block_index}:{call.lineno}: {name}: API is missing")
                continue
            try:
                signature = inspect.signature(value)
            except (TypeError, ValueError):
                continue
            try:
                signature.bind(
                    *([object()] * len(call.args)),
                    **{keyword.arg: object() for keyword in call.keywords if keyword.arg},
                )
            except TypeError as error:
                issues.append(f"{path}:{block_index}:{call.lineno}: {name}: {error}")

    assert not issues, "\n".join(issues)


def test_current_documentation_uses_current_distribution_and_registry_api() -> None:
    text = "\n".join(path.read_text(encoding="utf-8") for path in DOCUMENTS)

    assert not STALE_EXTRA.search(text)
    assert "registry.snapshot(" not in text


def test_getting_started_python_example_executes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    guide = ROOT / "docs" / "getting-started" / "index.md"
    source = next(
        source
        for _path, _index, source in _python_blocks((guide,))
        if "study = lc.SignalStudy(" in source
    )

    monkeypatch.chdir(tmp_path)
    exec(compile(source, str(guide), "exec"), {})

    assert (tmp_path / "lacuna-audit.html").is_file()
