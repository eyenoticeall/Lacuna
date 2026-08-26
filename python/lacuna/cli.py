"""Command-line entry points for the Lacuna foundation."""

from __future__ import annotations

import argparse
import json
import platform
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Literal, cast

import polars as pl

from lacuna import __version__
from lacuna.audit_profiles import standard_audit
from lacuna.bundle import verify_bundle
from lacuna.config import get_config
from lacuna.exceptions import DataContractError, LacunaError, ReportError
from lacuna.labels import PriceAdjustment
from lacuna.native import native_status
from lacuna.report import AuditReport
from lacuna.study import SignalStudy
from lacuna.types import AnalysisResult, FindingState, JsonValue

ReportFormat = Literal["json", "markdown", "html"]
_MAX_EVIDENCE_BYTES = 16 * 1024 * 1024


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


def _evidence_spec(value: str) -> tuple[str, str]:
    name, separator, path = value.partition("=")
    if not separator or not name or not path:
        raise argparse.ArgumentTypeError("evidence must use NAME=PATH")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", name):
        raise argparse.ArgumentTypeError(
            "evidence NAME must use 1-64 letters, digits, dots, underscores, or hyphens"
        )
    return name, path


def _load_evidence(specifications: Sequence[tuple[str, str]]) -> dict[str, AnalysisResult]:
    results: dict[str, AnalysisResult] = {}
    for name, raw_path in specifications:
        if name in results:
            raise DataContractError(f"duplicate evidence name {name!r}")
        path = Path(raw_path)
        try:
            size = path.stat().st_size
        except OSError as error:
            raise DataContractError(f"cannot inspect evidence file for {name!r}: {path}") from error
        if size > _MAX_EVIDENCE_BYTES:
            raise DataContractError(
                f"evidence file for {name!r} exceeds the {_MAX_EVIDENCE_BYTES}-byte limit"
            )
        try:
            content = path.read_text(encoding="utf-8")
            results[name] = AnalysisResult.from_json(content)
        except (OSError, UnicodeError, TypeError, ValueError) as error:
            raise DataContractError(
                f"invalid v1 evidence file for {name!r}: {path}: {error}"
            ) from error
    return results


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
    if arguments.bundle is not None:
        destination = report.bundle(arguments.bundle, overwrite=arguments.overwrite)
        print(f"wrote Lacuna reproducibility bundle to {destination}", file=sys.stderr)
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


def _run_standard_audit(arguments: argparse.Namespace) -> int:
    results = _load_evidence(arguments.evidence)
    report = standard_audit(results=results, scope=arguments.scope)
    if arguments.bundle is not None:
        destination = report.bundle(
            arguments.bundle,
            configuration={
                "audit_profile": f"standard.{arguments.scope}",
                "audit_profile_version": 1,
            },
            evidence=results,
            invocation={
                "command": "lacuna audit",
                "scope": arguments.scope,
                "evidence_names": tuple(sorted(results)),
            },
            overwrite=arguments.overwrite,
        )
        print(f"wrote Lacuna reproducibility bundle to {destination}", file=sys.stderr)
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


def _run_bundle_verify(arguments: argparse.Namespace) -> int:
    verification = verify_bundle(arguments.path)
    payload = verification.to_dict()
    if arguments.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    print(f"Bundle       {verification.path}")
    print(f"Format       {verification.manifest.format} v{verification.manifest.bundle_version}")
    print(f"Artifacts    {verification.artifact_count}")
    print(f"Total bytes  {verification.total_size}")
    print(f"SHA-256      {verification.archive_sha256}")
    print("Integrity    verified")
    print("Authenticity not verified (use signed release/provenance channels separately)")
    return 0


def _run_bench(arguments: argparse.Namespace) -> int:
    from lacuna.benchmark import benchmark_config_for_tier, run_benchmarks

    config = benchmark_config_for_tier(
        arguments.tier,
        repetitions=arguments.repetitions,
        warmups=arguments.warmups,
        seed=arguments.seed,
    )
    content = run_benchmarks(config, use_native=not arguments.no_native).to_json() + "\n"
    if arguments.out is None:
        print(content, end="")
        return 0
    destination = Path(arguments.out)
    destination.parent.mkdir(parents=True, exist_ok=True)
    mode = "w" if arguments.overwrite else "x"
    try:
        with destination.open(mode, encoding="utf-8", newline="\n") as output:
            output.write(content)
    except FileExistsError as error:
        raise ReportError(f"refusing to overwrite existing benchmark: {destination}") from error
    print(f"wrote Lacuna benchmark to {destination}", file=sys.stderr)
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lacuna",
        description="Quantitative research validation for finding where alpha breaks.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subcommands = parser.add_subparsers(dest="command")

    doctor = subcommands.add_parser("doctor", help="show build and runtime diagnostics")
    doctor.add_argument("--json", action="store_true", help="emit machine-readable JSON")

    audit = subcommands.add_parser(
        "audit",
        help="assemble a standardized cross-phase audit from result JSON evidence",
    )
    audit.add_argument(
        "--evidence",
        action="append",
        type=_evidence_spec,
        default=[],
        metavar="NAME=PATH",
        help="named AnalysisResult v1 JSON; repeat for multiple results",
    )
    audit.add_argument(
        "--scope",
        choices=("signal", "strategy", "options"),
        default="strategy",
        help="research scope controlling required, optional, and inapplicable evidence",
    )
    audit.add_argument("--no-color", action="store_true", help="disable terminal color")
    audit.add_argument(
        "--format",
        choices=("json", "markdown", "html"),
        help="report format; inferred from --out or Markdown on stdout",
    )
    audit.add_argument("--out", help="write the report to this path")
    audit.add_argument(
        "--bundle",
        help="also write a deterministic .lacuna reproducibility bundle",
    )
    audit.add_argument("--overwrite", action="store_true", help="replace an existing artifact")
    audit.add_argument(
        "--fail-on",
        choices=("never", "fail", "warn"),
        default="never",
        help="return exit code 3 when the selected finding state is present",
    )

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
    signal.add_argument(
        "--bundle",
        help="also write a deterministic .lacuna reproducibility bundle",
    )
    signal.add_argument("--overwrite", action="store_true", help="replace an existing report")
    signal.add_argument(
        "--fail-on",
        choices=("never", "fail", "warn"),
        default="never",
        help="return exit code 3 when the selected finding state is present",
    )

    bench = subcommands.add_parser("bench", help="run reproducible developer benchmarks")
    bench.add_argument(
        "--tier",
        choices=("smoke", "small", "medium"),
        default="smoke",
        help="deterministic dataset scale",
    )
    bench.add_argument("--repetitions", type=_positive_int, default=3)
    bench.add_argument("--warmups", type=_non_negative_int, default=1)
    bench.add_argument("--seed", type=_non_negative_int, default=42)
    bench.add_argument("--no-native", action="store_true", help="omit native benchmark cases")
    bench.add_argument("--out", help="write the benchmark JSON to this path")
    bench.add_argument("--overwrite", action="store_true", help="replace an existing artifact")

    bundle = subcommands.add_parser("bundle", help="inspect non-executable reproducibility bundles")
    bundle_subcommands = bundle.add_subparsers(dest="bundle_command", required=True)
    bundle_verify = bundle_subcommands.add_parser(
        "verify", help="verify structure and artifact SHA-256 digests"
    )
    bundle_verify.add_argument("path", help="path to a .lacuna bundle")
    bundle_verify.add_argument("--json", action="store_true", help="emit machine-readable JSON")
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

    if arguments.command == "audit":
        try:
            return _run_standard_audit(arguments)
        except (LacunaError, OSError) as error:
            print(f"lacuna: error: {error}", file=sys.stderr)
            return 1

    if arguments.command == "bench":
        try:
            return _run_bench(arguments)
        except (LacunaError, OSError, pl.exceptions.PolarsError) as error:
            print(f"lacuna: error: {error}", file=sys.stderr)
            return 1

    if arguments.command == "bundle":
        try:
            return _run_bundle_verify(arguments)
        except (LacunaError, OSError) as error:
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
