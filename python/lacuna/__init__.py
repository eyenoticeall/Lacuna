"""Public foundation API for Lacuna."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("lacuna")
except PackageNotFoundError:
    __version__ = "0.0.1"

from lacuna.config import Config, config, configure, get_config
from lacuna.types import AnalysisResult, Finding, FindingState, ResultMetadata, Severity

__all__ = [
    "AnalysisResult",
    "Config",
    "Finding",
    "FindingState",
    "ResultMetadata",
    "Severity",
    "__version__",
    "config",
    "configure",
    "get_config",
]
