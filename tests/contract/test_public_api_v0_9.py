from __future__ import annotations

import importlib
import inspect
import json
from pathlib import Path

import lacuna

CONTRACT_PATH = Path(__file__).parents[1] / "fixtures" / "public-api-v0.9.json"


def _contract() -> dict[str, object]:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def _resolve(module_name: str, qualname: str) -> object:
    value: object = importlib.import_module(module_name)
    for part in qualname.split("."):
        value = getattr(value, part)
    return value


def _signature(value: object) -> str:
    signature = inspect.signature(value)
    parameters = [
        parameter.replace(annotation=inspect.Parameter.empty)
        for parameter in signature.parameters.values()
    ]
    return str(
        signature.replace(
            parameters=parameters,
            return_annotation=inspect.Signature.empty,
        )
    )


def test_root_exports_preserve_the_v0_9_contract() -> None:
    expected = _contract()["root_exports"]
    assert isinstance(expected, list)
    assert set(expected).issubset(lacuna.__all__)


def test_public_module_exports_preserve_the_v0_9_contract() -> None:
    module_exports = _contract()["module_exports"]
    assert isinstance(module_exports, dict)
    for module_name, expected in module_exports.items():
        assert isinstance(module_name, str)
        assert isinstance(expected, list)
        observed = importlib.import_module(module_name).__all__
        assert set(expected).issubset(observed)


def test_new_public_call_signatures_match_the_v0_9_contract() -> None:
    callables = _contract()["callables"]
    assert isinstance(callables, list)
    observed = []
    for item in callables:
        assert isinstance(item, dict)
        module_name = item["module"]
        qualname = item["qualname"]
        assert isinstance(module_name, str)
        assert isinstance(qualname, str)
        observed.append(
            {
                "module": module_name,
                "qualname": qualname,
                "signature": _signature(_resolve(module_name, qualname)),
            }
        )
    assert observed == callables


def test_v0_9_contract_declares_its_compatibility_chain() -> None:
    assert _contract()["package_series"] == "0.9"
    assert _contract()["inherited_contracts"] == [
        "lacuna-public-api-v0.1",
        "lacuna-public-api-v0.2",
        "lacuna-public-api-v0.3",
        "lacuna-public-api-v0.4",
        "lacuna-public-api-v0.5",
        "lacuna-public-api-v0.6",
        "lacuna-public-api-v0.7",
        "lacuna-public-api-v0.8",
    ]
