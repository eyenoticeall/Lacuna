"""Exercise an installed Lacuna wheel without development dependencies."""

from __future__ import annotations

import importlib
import json
import math
from importlib import metadata
from importlib.resources import files

import numpy as np

import lacuna
from lacuna import _native
from lacuna.schemas import audit_result_v1_text

PUBLIC_MODULES = (
    "lacuna.adapters",
    "lacuna.audit",
    "lacuna.benchmark",
    "lacuna.cli",
    "lacuna.config",
    "lacuna.cv",
    "lacuna.labels",
    "lacuna.native",
    "lacuna.report",
    "lacuna.signal",
    "lacuna.study",
    "lacuna.validation",
)


def require(condition: bool, message: str) -> None:
    """Fail the artifact smoke check with a useful contract message."""

    if not condition:
        raise RuntimeError(message)


for module in PUBLIC_MODULES:
    importlib.import_module(module)

distribution_version = metadata.version("lacuna")
require(lacuna.__version__ == distribution_version, "package and distribution versions disagree")
require(_native.version() == distribution_version, "native and distribution versions disagree")
require(_native.checked_mean([1.0, 2.0, 3.0]) == 2.0, "native mean kernel failed")

rank_ic = _native.grouped_rank_ic(
    [1.0, 2.0, 3.0, 1.0, 2.0],
    [0.0, -0.0, 1.0, 0.0, -0.0],
    [0, 3, 5],
)
require(rank_ic[0] is not None, "native rank IC unexpectedly undefined")
require(math.isclose(rank_ic[0], math.sqrt(3.0) / 2.0, abs_tol=1e-14), "native rank IC failed")
require(rank_ic[1] is None, "signed-zero constant group must be undefined")

signal_result = lacuna.signal.ic(
    np.array([1.0, 2.0, 3.0]),
    np.array([1.0, 2.0, 3.0]),
    by=None,
    min_observations=2,
)
require(signal_result.metrics["mean_ic"] == 1.0, "public signal API failed")

package = files("lacuna")
require(package.joinpath("py.typed").is_file(), "wheel is missing py.typed")
require(package.joinpath("_native.pyi").is_file(), "wheel is missing native type stubs")
schema = json.loads(audit_result_v1_text())
require(schema.get("title") == "Lacuna audit result v1", "wheel is missing the audit schema")

print(
    json.dumps(
        {
            "distribution_version": distribution_version,
            "native_version": _native.version(),
            "public_modules": len(PUBLIC_MODULES),
            "schema": schema["title"],
            "signal_mean_ic": signal_result.metrics["mean_ic"],
        },
        indent=2,
        sort_keys=True,
    )
)
