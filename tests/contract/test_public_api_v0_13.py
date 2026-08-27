from __future__ import annotations

import json
from pathlib import Path

CONTRACT_PATH = Path(__file__).parents[1] / "fixtures" / "public-api-v0.13.json"


def test_v0_13_changes_distribution_identity_without_changing_import_api() -> None:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

    assert contract["package_series"] == "0.13"
    assert contract["callables"] == []
    assert contract["module_exports"] == {}
    assert contract["root_exports"] == []
    assert contract["inherited_contracts"][-1] == "lacuna-public-api-v0.12"
    assert len(contract["inherited_contracts"]) == 12
