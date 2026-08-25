from __future__ import annotations

import math

import pytest

from lacuna import _native
from lacuna.native import native_status


def test_native_extension_is_available() -> None:
    status = native_status()
    assert status.available is True
    assert status.version == _native.version()


def test_checked_mean_crosses_the_native_boundary() -> None:
    assert _native.checked_mean([1.0, 2.0, 6.0]) == 3.0


def test_checked_mean_rejects_non_finite_values() -> None:
    with pytest.raises(ValueError, match="index 1"):
        _native.checked_mean([1.0, math.nan])
