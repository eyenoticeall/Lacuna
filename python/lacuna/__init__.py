"""Public API for quantitative signal diagnostics and validation."""

from lacuna import (
    adapters,
    bias,
    bundle,
    costs,
    cv,
    experiment,
    labels,
    plugins,
    regime,
    robustness,
    signal,
    validation,
)
from lacuna._version import __version__
from lacuna.audit import (
    Applicability,
    ApplicabilityState,
    AuditContext,
    AuditRule,
    audit,
    default_rules,
    run_audit,
)
from lacuna.benchmark import (
    BenchmarkCase,
    BenchmarkConfig,
    BenchmarkSuite,
    benchmark_config_for_tier,
    run_benchmarks,
)
from lacuna.bundle import (
    BUNDLE_FORMAT,
    BUNDLE_VERSION,
    BundleArtifact,
    BundleManifest,
    BundleVerification,
    create_bundle,
    verify_bundle,
)
from lacuna.config import Config, config, configure, get_config
from lacuna.exceptions import (
    ConfigurationError,
    DataContractError,
    LacunaError,
    MethodContractError,
    NativeExtensionError,
    PluginError,
    ReportError,
)
from lacuna.experiment import ExperimentRegistry
from lacuna.labels import LabelResult
from lacuna.report import AuditReport
from lacuna.study import SignalStudy
from lacuna.types import AnalysisResult, Finding, FindingState, ResultMetadata, Severity

__all__ = [
    "BUNDLE_FORMAT",
    "BUNDLE_VERSION",
    "AnalysisResult",
    "Applicability",
    "ApplicabilityState",
    "AuditContext",
    "AuditReport",
    "AuditRule",
    "BenchmarkCase",
    "BenchmarkConfig",
    "BenchmarkSuite",
    "BundleArtifact",
    "BundleManifest",
    "BundleVerification",
    "Config",
    "ConfigurationError",
    "DataContractError",
    "ExperimentRegistry",
    "Finding",
    "FindingState",
    "LabelResult",
    "LacunaError",
    "MethodContractError",
    "NativeExtensionError",
    "PluginError",
    "ReportError",
    "ResultMetadata",
    "Severity",
    "SignalStudy",
    "__version__",
    "adapters",
    "audit",
    "benchmark_config_for_tier",
    "bias",
    "bundle",
    "config",
    "configure",
    "costs",
    "create_bundle",
    "cv",
    "default_rules",
    "experiment",
    "get_config",
    "labels",
    "plugins",
    "regime",
    "robustness",
    "run_audit",
    "run_benchmarks",
    "signal",
    "validation",
    "verify_bundle",
]
