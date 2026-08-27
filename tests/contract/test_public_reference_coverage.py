from __future__ import annotations

import importlib
import json
from collections.abc import Iterable
from pathlib import Path

import lacuna

ROOT = Path(__file__).parents[2]
MANIFEST_PATH = ROOT / "docs/reference/public-reference-coverage-v1.json"
FIXTURE_ROOT = ROOT / "tests/fixtures"


def _strict_object(pairs: Iterable[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate manifest key {key!r}")
        result[key] = value
    return result


def _manifest() -> dict[str, object]:
    payload = json.loads(
        MANIFEST_PATH.read_text(encoding="utf-8"),
        object_pairs_hook=_strict_object,
    )
    assert isinstance(payload, dict)
    return payload


def _contracts() -> tuple[dict[str, object], ...]:
    return tuple(
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(FIXTURE_ROOT.glob("public-api-v0.*.json"))
    )


def _record(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    assert set(value) == {"module", "reference", "design", "exports"}
    assert isinstance(value["module"], str)
    assert isinstance(value["reference"], str)
    assert isinstance(value["design"], str)
    exports = value["exports"]
    assert isinstance(exports, list)
    assert exports
    assert all(isinstance(item, str) and item for item in exports)
    assert len(exports) == len(set(exports))
    return value


def _section(text: str, module_name: str) -> str:
    heading = f"## `{module_name}`\n"
    start = text.find(heading)
    assert start >= 0, f"reference page has no section for {module_name}"
    end = text.find("\n## ", start + len(heading))
    return text[start:] if end < 0 else text[start:end]


def test_manifest_identity_and_cumulative_contract_chain() -> None:
    manifest = _manifest()
    assert set(manifest) == {
        "format",
        "manifest_version",
        "package_series",
        "root",
        "modules",
    }
    assert manifest["format"] == "lacuna.public-reference-coverage"
    assert manifest["manifest_version"] == 1
    assert manifest["package_series"] == "0.14"

    root = _record(manifest["root"])
    root_exports = root["exports"]
    assert root["module"] == "lacuna"
    assert isinstance(root_exports, list)
    assert tuple(root_exports) == tuple(lacuna.__all__)

    contracts = _contracts()
    inherited_root = {
        export
        for contract in contracts
        for export in contract["root_exports"]  # type: ignore[union-attr]
    }
    assert set(root_exports) == inherited_root


def test_every_supported_module_has_exact_exports_and_existing_routes() -> None:
    manifest = _manifest()
    raw_modules = manifest["modules"]
    assert isinstance(raw_modules, list)
    modules = tuple(_record(item) for item in raw_modules)
    names = tuple(record["module"] for record in modules)
    assert names == tuple(sorted(names))
    assert len(names) == len(set(names))

    contracted_modules = {
        module_name
        for contract in _contracts()
        for module_name in contract["module_exports"]  # type: ignore[union-attr]
    }
    assert set(names) == contracted_modules

    for record in modules:
        module_name = record["module"]
        exports = record["exports"]
        reference = record["reference"]
        design = record["design"]
        assert isinstance(module_name, str)
        assert isinstance(exports, list)
        assert isinstance(reference, str)
        assert isinstance(design, str)
        module = importlib.import_module(module_name)
        assert tuple(exports) == tuple(module.__all__)
        assert (ROOT / reference).is_file()
        assert (ROOT / design).is_file()


def test_reference_page_mentions_every_manifest_export_in_its_module_section() -> None:
    manifest = _manifest()
    root = _record(manifest["root"])
    raw_modules = manifest["modules"]
    assert isinstance(raw_modules, list)
    records = (root, *(_record(item) for item in raw_modules))
    reference_path = ROOT / str(root["reference"])
    text = reference_path.read_text(encoding="utf-8")

    for record in records:
        module_name = record["module"]
        exports = record["exports"]
        assert isinstance(module_name, str)
        assert isinstance(exports, list)
        section = _section(text, module_name)
        missing = [export for export in exports if f"`{export}`" not in section]
        assert not missing, f"{module_name} reference is missing exports: {missing}"
