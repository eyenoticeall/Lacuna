"""Packaged machine-readable compatibility schemas."""

from __future__ import annotations

from importlib.resources import files


def audit_result_v1_text() -> str:
    """Return the published audit-result v1 JSON Schema text."""

    return files(__package__).joinpath("audit-result-v1.schema.json").read_text(encoding="utf-8")


def bundle_manifest_v1_text() -> str:
    """Return the published reproducibility-bundle manifest v1 JSON Schema text."""

    return (
        files(__package__)
        .joinpath("lacuna-bundle-manifest-v1.schema.json")
        .read_text(encoding="utf-8")
    )


__all__ = ["audit_result_v1_text", "bundle_manifest_v1_text"]
