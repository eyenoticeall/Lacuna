from __future__ import annotations

import importlib
import inspect
import json
from pathlib import Path

import lacuna_options

CONTRACT_PATH = Path(__file__).parent / "fixtures" / "public-api-v0.2.json"


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


def test_root_exports_exactly_match_the_v0_2_contract() -> None:
    expected = _contract()["module_exports"]
    assert isinstance(expected, list)
    assert lacuna_options.__all__ == expected


def test_public_call_signatures_match_the_v0_2_contract() -> None:
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


def test_v0_2_contract_inherits_the_complete_v0_1_api() -> None:
    contract = _contract()
    assert contract["package_series"] == "0.2"
    assert contract["inherited_contracts"] == ["lacuna-options-public-api-v0.1"]
