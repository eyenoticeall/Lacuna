"""Public API for quantitative signal diagnostics and validation."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("lacuna")
except PackageNotFoundError:
    __version__ = "0.0.1"

from lacuna import cv, labels, signal, validation
from lacuna.audit import (
    Applicability,
    ApplicabilityState,
    AuditContext,
    AuditRule,
    audit,
    default_rules,
    run_audit,
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
    "Config",
    "ConfigurationError",
    "DataContractError",
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
    "config",
    "configure",
    "cv",
    "default_rules",
    "get_config",
    "labels",
    "run_audit",
    "signal",
    "validation",
]
