"""Lacuna's public exception hierarchy."""


class LacunaError(Exception):
    """Base class for errors raised by Lacuna."""


class ConfigurationError(LacunaError, ValueError):
    """Raised when runtime configuration is invalid."""


class DataContractError(LacunaError, ValueError):
    """Raised when input data does not satisfy a declared semantic contract."""


class MethodContractError(LacunaError, ValueError):
    """Raised when an analytical method or its configuration is undefined."""


class NativeExtensionError(LacunaError, RuntimeError):
    """Reserved for a required native capability that is unavailable.

    No current code path raises it: native kernels fall back to the reference
    implementation and record the backend used.
    """


class ReportError(LacunaError, RuntimeError):
    """Raised when a report cannot be rendered or persisted safely."""


class PluginError(LacunaError, RuntimeError):
    """Raised when plugin discovery, negotiation, or explicit activation fails."""
