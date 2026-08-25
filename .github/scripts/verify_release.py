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
OPTIONS_ROOT = Path("extensions/lacuna-options")


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


def options_version(root: Path) -> str:
    """Verify and return the independent lacuna-options release identity."""

    options_root = root / OPTIONS_ROOT
    pyproject = tomllib.loads((options_root / "pyproject.toml").read_text(encoding="utf-8"))
    project_version = pyproject["project"]["version"]
    source_version = _python_source_version(options_root / "src/lacuna_options/_version.py")
    if project_version != source_version:
        fail(
            "lacuna-options versions disagree: "
            f"pyproject={project_version}, source={source_version}"
        )
    if re.fullmatch(r"\d+\.\d+\.\d+", project_version) is None:
        fail(f"unsupported lacuna-options release version: {project_version!r}")
    changelog = (options_root / "CHANGELOG.md").read_text(encoding="utf-8")
    if f"## [{project_version}] - " not in changelog:
        fail(f"lacuna-options CHANGELOG has no dated release heading for {project_version}")
    return project_version


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
    options_version(root)

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


def _wheel_metadata(archive: zipfile.ZipFile) -> tuple[str, str, str]:
    metadata_paths = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
    wheel_paths = [name for name in archive.namelist() if name.endswith(".dist-info/WHEEL")]
    if len(metadata_paths) != 1 or len(wheel_paths) != 1:
        fail("wheel must contain exactly one METADATA and one WHEEL file")
    metadata = BytesParser().parsebytes(archive.read(metadata_paths[0]))
    wheel = BytesParser().parsebytes(archive.read(wheel_paths[0]))
    return str(metadata["Name"]), str(metadata["Version"]), str(wheel["Tag"])


def _verify_wheel(path: Path, version: str, expected_platform: str) -> None:
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        metadata_name, metadata_version, wheel_tag = _wheel_metadata(archive)
        if metadata_name != "lacuna":
            fail(f"{path.name} distribution name is {metadata_name!r}, expected 'lacuna'")
        if metadata_version != version:
            fail(f"{path.name} metadata version is {metadata_version!r}, expected {version!r}")
        expected_tag = f"cp311-abi3-{expected_platform}"
        if wheel_tag != expected_tag:
            fail(f"{path.name} wheel tag is {wheel_tag!r}, expected {expected_tag!r}")
        required = {
            "lacuna/__init__.py",
            "lacuna/_advanced_inference.py",
            "lacuna/_native.pyi",
            "lacuna/_version.py",
            "lacuna/bias.py",
            "lacuna/costs.py",
            "lacuna/cv.py",
            "lacuna/experiment.py",
            "lacuna/plugins.py",
            "lacuna/py.typed",
            "lacuna/regime.py",
            "lacuna/robustness.py",
            "lacuna/validation.py",
            "lacuna/adapters/backtest.py",
            "lacuna/adapters/duckdb.py",
            "lacuna/adapters/sklearn.py",
            "lacuna/adapters/vendor.py",
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
        f"{prefix}python/lacuna/_advanced_inference.py",
        f"{prefix}python/lacuna/_native.pyi",
        f"{prefix}python/lacuna/_version.py",
        f"{prefix}python/lacuna/bias.py",
        f"{prefix}python/lacuna/costs.py",
        f"{prefix}python/lacuna/cv.py",
        f"{prefix}python/lacuna/experiment.py",
        f"{prefix}python/lacuna/plugins.py",
        f"{prefix}python/lacuna/py.typed",
        f"{prefix}python/lacuna/regime.py",
        f"{prefix}python/lacuna/robustness.py",
        f"{prefix}python/lacuna/validation.py",
        f"{prefix}python/lacuna/adapters/backtest.py",
        f"{prefix}python/lacuna/adapters/duckdb.py",
        f"{prefix}python/lacuna/adapters/sklearn.py",
        f"{prefix}python/lacuna/adapters/vendor.py",
        f"{prefix}rust/lacuna-core/src/lib.rs",
        f"{prefix}rust/lacuna-python/src/lib.rs",
        f"{prefix}schemas/audit-result-v1.schema.json",
    }
    with tarfile.open(path, mode="r:gz") as archive:
        names = {member.name for member in archive.getmembers()}
    missing = sorted(required.difference(names))
    if missing:
        fail(f"{path.name} is missing source resources: {', '.join(missing)}")


def _verify_options_wheel(path: Path, version: str) -> None:
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        metadata_name, metadata_version, wheel_tag = _wheel_metadata(archive)
        if metadata_name != "lacuna-options":
            fail(f"{path.name} distribution name is {metadata_name!r}, expected 'lacuna-options'")
        if metadata_version != version:
            fail(f"{path.name} metadata version is {metadata_version!r}, expected {version!r}")
        if wheel_tag != "py3-none-any":
            fail(f"{path.name} wheel tag is {wheel_tag!r}, expected 'py3-none-any'")
        required = {
            "lacuna_options/__init__.py",
            "lacuna_options/_version.py",
            "lacuna_options/chain.py",
            "lacuna_options/py.typed",
        }
        missing = sorted(required.difference(names))
        if missing:
            fail(f"{path.name} is missing packaged resources: {', '.join(missing)}")


def _verify_options_sdist(path: Path, version: str) -> None:
    prefix = f"lacuna_options-{version}/"
    required = {
        f"{prefix}CHANGELOG.md",
        f"{prefix}README.md",
        f"{prefix}pyproject.toml",
        f"{prefix}src/lacuna_options/__init__.py",
        f"{prefix}src/lacuna_options/_version.py",
        f"{prefix}src/lacuna_options/chain.py",
        f"{prefix}src/lacuna_options/py.typed",
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
    extension_version = options_version(root)
    wheels = sorted(dist.glob("*.whl"))
    sdists = sorted(dist.glob("*.tar.gz"))
    expected_wheel_count = len(EXPECTED_WHEEL_PLATFORMS) + 1
    if len(wheels) != expected_wheel_count:
        fail(f"expected {expected_wheel_count} wheels, found {len(wheels)}")
    expected_sdists = {
        f"lacuna-{version}.tar.gz",
        f"lacuna_options-{extension_version}.tar.gz",
    }
    observed_sdists = {path.name for path in sdists}
    if observed_sdists != expected_sdists:
        fail(
            "source distribution set does not match: "
            f"missing={sorted(expected_sdists - observed_sdists)}, "
            f"unexpected={sorted(observed_sdists - expected_sdists)}"
        )

    expected_wheels = {
        f"lacuna-{version}-cp311-abi3-{platform}.whl": platform
        for platform in EXPECTED_WHEEL_PLATFORMS
    }
    options_wheel_name = f"lacuna_options-{extension_version}-py3-none-any.whl"
    observed_names = {path.name for path in wheels}
    all_expected_wheels = {*expected_wheels, options_wheel_name}
    if observed_names != all_expected_wheels:
        fail(
            "wheel set does not match the release matrix: "
            f"missing={sorted(all_expected_wheels - observed_names)}, "
            f"unexpected={sorted(observed_names - all_expected_wheels)}"
        )
    for wheel in wheels:
        if wheel.name == options_wheel_name:
            _verify_options_wheel(wheel, extension_version)
        else:
            _verify_wheel(wheel, version, expected_wheels[wheel.name])
    _verify_sdist(dist / f"lacuna-{version}.tar.gz", version)
    _verify_options_sdist(
        dist / f"lacuna_options-{extension_version}.tar.gz",
        extension_version,
    )
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
