"""Enforce the reviewed PyO3/NumPy boundary dependency contract."""

from __future__ import annotations

import json
import subprocess
import tomllib
from pathlib import Path
from typing import NoReturn

ROOT = Path(__file__).parents[2]
MANIFEST = ROOT / "rust/lacuna-python/Cargo.toml"
EXPECTED = {
    "numpy": {"version": "0.29.0", "license": "BSD-2-Clause"},
    "pyo3": {"version": "0.29.2", "license": "MIT OR Apache-2.0"},
}


def fail(message: str) -> NoReturn:
    raise RuntimeError(message)


def main() -> None:
    manifest = tomllib.loads(MANIFEST.read_text(encoding="utf-8"))
    dependencies = manifest["dependencies"]
    numpy_requirement = dependencies.get("numpy")
    pyo3_requirement = dependencies.get("pyo3")
    if numpy_requirement != "0.29.0":
        fail("the reviewed Rust numpy boundary must remain on numpy 0.29.0")
    if not isinstance(pyo3_requirement, dict):
        fail("pyo3 must use an explicit reviewed dependency table")
    if pyo3_requirement.get("version") != "0.29.2":
        fail("the reviewed Rust boundary must remain on PyO3 0.29.2")
    if pyo3_requirement.get("features") != ["abi3-py311"]:
        fail("the native binding must expose exactly the abi3-py311 compatibility feature")

    metadata = json.loads(
        subprocess.run(
            ["cargo", "metadata", "--locked", "--format-version=1"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    packages = {
        (package["name"], package["version"]): package
        for package in metadata["packages"]
        if package.get("source") is not None
    }
    for name, contract in EXPECTED.items():
        version = contract["version"]
        package = packages.get((name, version))
        if package is None:
            fail(f"Cargo.lock does not resolve reviewed dependency {name} {version}")
        if package.get("source") != "registry+https://github.com/rust-lang/crates.io-index":
            fail(f"{name} must resolve from the reviewed crates.io registry")
        if package.get("license") != contract["license"]:
            fail(
                f"{name} license changed from {contract['license']!r} to {package.get('license')!r}"
            )
    print(json.dumps({"dependencies": EXPECTED, "status": "verified"}, sort_keys=True))


if __name__ == "__main__":
    main()
