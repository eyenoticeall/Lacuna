from __future__ import annotations

import json

from lacuna.cli import main


def test_doctor_has_machine_readable_output(capsys: object) -> None:
    assert main(["doctor", "--json"]) == 0
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    payload = json.loads(captured.out)
    assert "lacuna_version" in payload
    assert "native" in payload
