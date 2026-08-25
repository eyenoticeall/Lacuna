"""Public API for quantitative signal diagnostics and validation."""

from lacuna import cv, experiment, labels, regime, robustness, signal, validation
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
from lacuna.config import Config, config, configure, get_config
from lacuna.exceptions import (
    ConfigurationError,
    DataContractError,
    LacunaError,
    MethodContractError,
    NativeExtensionError,
    ReportError,
)
from lacuna.experiment import ExperimentRegistry
from lacuna.labels import LabelResult
from lacuna.report import AuditReport
from lacuna.study import SignalStudy
from lacuna.types import AnalysisResult, Finding, FindingState, ResultMetadata, Severity

__all__ = [
    "AnalysisResult",
    "Applicability",
    "ApplicabilityState",
    "AuditContext",
    "AuditReport",
    "AuditRule",
    "BenchmarkCase",
    "BenchmarkConfig",
    "BenchmarkSuite",
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
    "ReportError",
    "ResultMetadata",
    "Severity",
    "SignalStudy",
    "__version__",
    "audit",
    "benchmark_config_for_tier",
    "config",
    "configure",
    "cv",
    "default_rules",
    "experiment",
    "get_config",
    "labels",
    "regime",
    "robustness",
    "run_audit",
    "run_benchmarks",
    "signal",
    "validation",
]
