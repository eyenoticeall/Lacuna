"""Verify Lacuna release identity and the complete distribution set."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import subprocess
import tarfile
import tomllib
import zipfile
from email.parser import BytesParser
from pathlib import Path
from typing import NoReturn

EXPECTED_WHEEL_PLATFORMS = (
    "manylinux_2_28_x86_64",
    "manylinux_2_28_aarch64",
    "macosx_11_0_arm64",
    "win_amd64",
)


def fail(message: str) -> NoReturn:
    raise RuntimeError(message)


def python_version_from_cargo(version: str) -> str:
    match = re.fullmatch(r"(?P<release>\d+\.\d+\.\d+)-rc\.(?P<candidate>\d+)", version)
    if match is not None:
        return f"{match.group('release')}rc{match.group('candidate')}"
    if re.fullmatch(r"\d+\.\d+\.\d+", version) is None:
        fail(f"unsupported Cargo release version: {version!r}")
    return version


def _python_source_version(path: Path) -> str:
    module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in module.body:
        if isinstance(node, ast.Assign):
            names = [target.id for target in node.targets if isinstance(target, ast.Name)]
            if (
                "__version__" in names
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                return node.value.value
    fail(f"{path} does not declare a literal __version__")


def _tag_target(root: Path, tag: str) -> str:
    process = subprocess.run(
        ["git", "rev-parse", f"refs/tags/{tag}^{{commit}}"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if process.returncode:
        fail(f"release tag does not exist locally: {tag}")
    return process.stdout.strip()


def verify_source(root: Path, tag: str, *, require_tag: bool) -> str:
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    cargo = tomllib.loads((root / "Cargo.toml").read_text(encoding="utf-8"))
    python_version = pyproject["project"]["version"]
    cargo_version = cargo["workspace"]["package"]["version"]
    source_version = _python_source_version(root / "python/lacuna/_version.py")
    expected_python_version = python_version_from_cargo(cargo_version)

    if python_version != expected_python_version or source_version != expected_python_version:
        fail(
            "release versions disagree: "
            f"pyproject={python_version}, Cargo={cargo_version}, source={source_version}"
        )
    expected_tag = f"v{cargo_version}"
    if tag != expected_tag:
        fail(f"tag {tag!r} does not match expected release tag {expected_tag!r}")

    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    if f"## [{cargo_version}] - " not in changelog:
        fail(f"CHANGELOG.md has no dated release heading for {cargo_version}")

    release_numbers = cargo_version.split("-", maxsplit=1)[0].split(".")
    release_series = ".".join(release_numbers[:2])
    contract_path = root / f"tests/fixtures/public-api-v{release_series}.json"
    if not contract_path.is_file():
        fail(f"public API contract does not exist for release series {release_series}")
    api_contract = json.loads(contract_path.read_text(encoding="utf-8"))
    if not python_version.startswith(f"{api_contract['package_series']}."):
        fail("public API contract package series does not match the release")

    if require_tag:
        tag_target = _tag_target(root, tag)
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if tag_target != head:
            fail(f"tag {tag!r} points to {tag_target}, not checked-out commit {head}")
    return python_version


def _wheel_metadata(archive: zipfile.ZipFile) -> tuple[str, str]:
    metadata_paths = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
    wheel_paths = [name for name in archive.namelist() if name.endswith(".dist-info/WHEEL")]
    if len(metadata_paths) != 1 or len(wheel_paths) != 1:
        fail("wheel must contain exactly one METADATA and one WHEEL file")
    metadata = BytesParser().parsebytes(archive.read(metadata_paths[0]))
    wheel = BytesParser().parsebytes(archive.read(wheel_paths[0]))
    return str(metadata["Version"]), str(wheel["Tag"])


def _verify_wheel(path: Path, version: str, expected_platform: str) -> None:
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        metadata_version, wheel_tag = _wheel_metadata(archive)
        if metadata_version != version:
            fail(f"{path.name} metadata version is {metadata_version!r}, expected {version!r}")
        expected_tag = f"cp311-abi3-{expected_platform}"
        if wheel_tag != expected_tag:
            fail(f"{path.name} wheel tag is {wheel_tag!r}, expected {expected_tag!r}")
        required = {
            "lacuna/__init__.py",
            "lacuna/_native.pyi",
            "lacuna/_version.py",
            "lacuna/experiment.py",
            "lacuna/py.typed",
            "lacuna/regime.py",
            "lacuna/robustness.py",
            "lacuna/schemas/audit-result-v1.schema.json",
        }
        missing = sorted(required.difference(names))
        if missing:
            fail(f"{path.name} is missing packaged resources: {', '.join(missing)}")
        native_suffix = ".pyd" if expected_platform == "win_amd64" else ".so"
        if not any(
            name.startswith("lacuna/_native") and name.endswith(native_suffix) for name in names
        ):
            fail(f"{path.name} is missing its native extension")


def _verify_sdist(path: Path, version: str) -> None:
    prefix = f"lacuna-{version}/"
    required = {
        f"{prefix}Cargo.toml",
        f"{prefix}CHANGELOG.md",
        f"{prefix}LICENSE-APACHE",
        f"{prefix}LICENSE-MIT",
        f"{prefix}README.md",
        f"{prefix}pyproject.toml",
        f"{prefix}python/lacuna/__init__.py",
        f"{prefix}python/lacuna/_native.pyi",
        f"{prefix}python/lacuna/_version.py",
        f"{prefix}python/lacuna/experiment.py",
        f"{prefix}python/lacuna/py.typed",
        f"{prefix}python/lacuna/regime.py",
        f"{prefix}python/lacuna/robustness.py",
        f"{prefix}rust/lacuna-core/src/lib.rs",
        f"{prefix}rust/lacuna-python/src/lib.rs",
        f"{prefix}schemas/audit-result-v1.schema.json",
    }
    with tarfile.open(path, mode="r:gz") as archive:
        names = {member.name for member in archive.getmembers()}
    missing = sorted(required.difference(names))
    if missing:
        fail(f"{path.name} is missing source resources: {', '.join(missing)}")


def _write_checksums(paths: list[Path], destination: Path) -> None:
    lines = []
    for path in sorted(paths, key=lambda item: item.name):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.name}")
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def verify_artifacts(root: Path, dist: Path, tag: str) -> str:
    version = verify_source(root, tag, require_tag=False)
    wheels = sorted(dist.glob("*.whl"))
    sdists = sorted(dist.glob("*.tar.gz"))
    if len(wheels) != len(EXPECTED_WHEEL_PLATFORMS):
        fail(f"expected {len(EXPECTED_WHEEL_PLATFORMS)} wheels, found {len(wheels)}")
    if len(sdists) != 1 or sdists[0].name != f"lacuna-{version}.tar.gz":
        fail(f"expected exactly lacuna-{version}.tar.gz")

    expected_wheels = {
        f"lacuna-{version}-cp311-abi3-{platform}.whl": platform
        for platform in EXPECTED_WHEEL_PLATFORMS
    }
    observed_names = {path.name for path in wheels}
    if observed_names != set(expected_wheels):
        fail(
            "wheel set does not match the release matrix: "
            f"missing={sorted(set(expected_wheels) - observed_names)}, "
            f"unexpected={sorted(observed_names - set(expected_wheels))}"
        )
    for wheel in wheels:
        _verify_wheel(wheel, version, expected_wheels[wheel.name])
    _verify_sdist(sdists[0], version)
    _write_checksums([*wheels, *sdists], dist / "SHA256SUMS")
    return version


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("--root", type=Path, default=Path.cwd())
    commands = root.add_subparsers(dest="command", required=True)
    source = commands.add_parser("source", help="verify version, changelog, API, and tag identity")
    source.add_argument("--tag", required=True)
    source.add_argument("--require-tag", action="store_true")
    artifacts = commands.add_parser("artifacts", help="verify wheels and source distribution")
    artifacts.add_argument("--tag", required=True)
    artifacts.add_argument("--dist", type=Path, required=True)
    return root


def main() -> None:
    arguments = parser().parse_args()
    root = arguments.root.resolve()
    if arguments.command == "source":
        version = verify_source(root, arguments.tag, require_tag=arguments.require_tag)
    else:
        version = verify_artifacts(root, arguments.dist.resolve(), arguments.tag)
    print(json.dumps({"release_version": version, "status": "verified"}, sort_keys=True))


if __name__ == "__main__":
    main()
