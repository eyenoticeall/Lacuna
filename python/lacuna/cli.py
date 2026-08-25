"""Command-line entry points for the Lacuna foundation."""

from __future__ import annotations

import argparse
import json
import platform
from collections.abc import Sequence

from lacuna import __version__
from lacuna.config import get_config
from lacuna.native import native_status


def _doctor_payload() -> dict[str, object]:
    configuration = get_config()
    native = native_status()
    return {
        "lacuna_version": __version__,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "native": {
            "available": native.available,
            "version": native.version,
            "error": native.error,
        },
        "config": {
            "threads": configuration.threads,
            "seed": configuration.seed,
            "memory_limit": configuration.memory_limit,
            "cache_dir": configuration.cache_dir,
            "log_level": configuration.log_level,
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lacuna",
        description="Quantitative research validation for finding where alpha breaks.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subcommands = parser.add_subparsers(dest="command")

    doctor = subcommands.add_parser("doctor", help="show build and runtime diagnostics")
    doctor.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the Lacuna command-line interface."""

    parser = _parser()
    arguments = parser.parse_args(argv)
    if arguments.command != "doctor":
        parser.print_help()
        return 0

    payload = _doctor_payload()
    if arguments.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    native = payload["native"]
    assert isinstance(native, dict)
    print(f"Lacuna       {payload['lacuna_version']}")
    print(f"Python       {payload['python_version']}")
    print(f"Platform     {payload['platform']}")
    print(f"Native core  {'available' if native['available'] else 'unavailable'}")
    if native["version"]:
        print(f"Native ver.  {native['version']}")
    return 0
