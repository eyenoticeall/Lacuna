"""Command-line entry points for the Lacuna foundation."""

from __future__ import annotations

import argparse
import json
import platform
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Literal, cast

import polars as pl

from lacuna import __version__
from lacuna.config import get_config
from lacuna.exceptions import DataContractError, LacunaError
from lacuna.labels import PriceAdjustment
from lacuna.native import native_status
from lacuna.report import AuditReport
from lacuna.study import SignalStudy
from lacuna.types import FindingState, JsonValue

ReportFormat = Literal["json", "markdown", "html"]


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def _resample_count(value: str) -> int:
    parsed = int(value)
    if parsed < 100:
        raise argparse.ArgumentTypeError("bootstrap resamples must be at least 100")
    return parsed


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be non-negative")
    return parsed


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


def _scan_frame(path: str) -> pl.LazyFrame:
    source = Path(path)
    suffix = source.suffix.lower()
    if suffix in {".parquet", ".pq"}:
        return pl.scan_parquet(source)
    if suffix == ".csv":
        return pl.scan_csv(source)
    if suffix in {".arrow", ".feather", ".ipc"}:
        return pl.scan_ipc(source)
    raise DataContractError(
        f"unsupported input format {suffix or '<none>'!r} for {source}; "
        "use Parquet, CSV, Arrow IPC, or Feather"
    )


def _render_report(report: AuditReport, selected: ReportFormat) -> str:
    if selected == "json":
        return report.to_json() + "\n"
    if selected == "html":
        return report.to_html()
    return report.to_markdown()


def _audit_exit_code(report: AuditReport, fail_on: str) -> int:
    states = {finding.state for finding in report.findings}
    if fail_on == "fail" and FindingState.FAIL in states:
        return 3
    if fail_on == "warn" and states.intersection({FindingState.FAIL, FindingState.WARN}):
        return 3
    return 0


def _run_signal(arguments: argparse.Namespace) -> int:
    horizons = tuple(arguments.horizon or ("1D", "5D", "20D"))
    study = SignalStudy(
        signal=_scan_frame(arguments.signal),
        prices=_scan_frame(arguments.prices),
        horizons=horizons,
        signal_time=arguments.signal_time,
        price_time=arguments.price_time,
        instrument=arguments.instrument,
        signal_value=arguments.signal_value,
        price=arguments.price,
        entry=arguments.entry,
        signal_observed_at=cast(Literal["open", "close"] | None, arguments.signal_observed_at),
        price_adjustment=cast(PriceAdjustment, arguments.price_adjustment),
        delisting_return=arguments.delisting_return,
        missing=cast(Literal["drop", "raise"], arguments.missing),
        allow_same_close=arguments.allow_same_close,
        quantiles=arguments.quantiles,
    )
    policies: dict[str, JsonValue] = {}
    if arguments.survivorship_safe is not None:
        policies["survivorship_safe"] = arguments.survivorship_safe
    if arguments.trial_history_available is not None:
        policies["trial_history_available"] = arguments.trial_history_available
    report = study.audit(
        bootstrap_resamples=arguments.bootstrap_resamples,
        seed=arguments.seed,
        policies=policies,
        use_native=not arguments.no_native,
    )
    if arguments.out is not None:
        destination = report.write(
            arguments.out,
            format=arguments.format,
            overwrite=arguments.overwrite,
        )
        print(f"wrote Lacuna audit to {destination}", file=sys.stderr)
    else:
        selected = cast(ReportFormat, arguments.format or "markdown")
        print(_render_report(report, selected), end="")
    return _audit_exit_code(report, arguments.fail_on)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lacuna",
        description="Quantitative research validation for finding where alpha breaks.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subcommands = parser.add_subparsers(dest="command")

    doctor = subcommands.add_parser("doctor", help="show build and runtime diagnostics")
    doctor.add_argument("--json", action="store_true", help="emit machine-readable JSON")

    signal = subcommands.add_parser(
        "signal",
        help="analyze a cross-sectional signal against a price panel",
    )
    signal.add_argument("--signal", required=True, help="signal data file")
    signal.add_argument("--prices", required=True, help="price data file")
    signal.add_argument(
        "--horizon",
        action="append",
        help="forward horizon such as 5D; repeat for multiple horizons",
    )
    signal.add_argument("--signal-time", default="time", help="signal observation-time column")
    signal.add_argument("--price-time", default="time", help="price observation-time column")
    signal.add_argument("--instrument", default="instrument", help="instrument identity column")
    signal.add_argument("--signal-value", default="signal", help="numeric signal column")
    signal.add_argument("--price", default="close", help="price column used for close exits")
    signal.add_argument(
        "--entry",
        choices=("current_close", "next_close", "next_open"),
        help="explicit label entry convention",
    )
    signal.add_argument(
        "--signal-observed-at",
        choices=("open", "close"),
        help="market phase when the signal becomes observable",
    )
    signal.add_argument(
        "--price-adjustment",
        choices=("raw", "split_adjusted", "total_return_adjusted", "unknown"),
        default="unknown",
        help="corporate-action semantics of the price field",
    )
    signal.add_argument(
        "--delisting-return",
        help="optional column containing terminal delisting returns",
    )
    signal.add_argument(
        "--missing",
        choices=("drop", "raise"),
        default="drop",
        help="missing-price policy",
    )
    signal.add_argument(
        "--allow-same-close",
        action="store_true",
        help="allow a close-observed signal to enter at that same close",
    )
    signal.add_argument("--quantiles", type=_positive_int, default=5)
    signal.add_argument("--bootstrap-resamples", type=_resample_count, default=1_000)
    signal.add_argument("--seed", type=_non_negative_int)
    signal.add_argument(
        "--survivorship-safe",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="declare whether historical-universe construction is survivorship-safe",
    )
    signal.add_argument(
        "--trial-history-available",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="declare whether complete research trial history is available",
    )
    signal.add_argument("--no-native", action="store_true", help="use Python references only")
    signal.add_argument("--no-color", action="store_true", help="disable terminal color")
    signal.add_argument(
        "--format",
        choices=("json", "markdown", "html"),
        help="report format; inferred from --out or Markdown on stdout",
    )
    signal.add_argument("--out", help="write the report to this path")
    signal.add_argument("--overwrite", action="store_true", help="replace an existing report")
    signal.add_argument(
        "--fail-on",
        choices=("never", "fail", "warn"),
        default="never",
        help="return exit code 3 when the selected finding state is present",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the Lacuna command-line interface."""

    parser = _parser()
    arguments = parser.parse_args(argv)
    if arguments.command is None:
        parser.print_help()
        return 0

    if arguments.command == "signal":
        try:
            return _run_signal(arguments)
        except (LacunaError, OSError, pl.exceptions.PolarsError) as error:
            print(f"lacuna: error: {error}", file=sys.stderr)
            return 1

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
