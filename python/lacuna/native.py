"""Safe access to the optional compiled extension."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NativeStatus:
    """Availability and version information for Lacuna's native core."""

    available: bool
    version: str | None
    error: str | None = None


def native_status() -> NativeStatus:
    """Inspect the native extension without making package import fragile."""

    try:
        from lacuna import _native
    except ImportError as error:
        return NativeStatus(available=False, version=None, error=str(error))
    return NativeStatus(available=True, version=_native.version())
