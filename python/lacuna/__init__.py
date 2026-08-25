"""Public API for quantitative signal diagnostics and validation."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("lacuna")
except PackageNotFoundError:
    __version__ = "0.0.1"

from lacuna import cv, labels, signal, validation
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
from lacuna.types import AnalysisResult, Finding, FindingState, ResultMetadata, Severity

__all__ = [
    "AnalysisResult",
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
    "__version__",
    "config",
    "configure",
    "cv",
    "get_config",
    "labels",
    "signal",
    "validation",
]
