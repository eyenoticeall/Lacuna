"""Metadata-only plugin discovery and explicit trusted-code activation."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from importlib import metadata
from types import MappingProxyType
from typing import Literal, cast

from lacuna.exceptions import MethodContractError, PluginError
from lacuna.types import AnalysisResult, JsonValue, ResultMetadata

PluginGroup = Literal[
    "adapters",
    "audit_rules",
    "cost_models",
    "methods",
    "report_sections",
]

ENTRY_POINT_GROUPS: Mapping[PluginGroup, str] = MappingProxyType(
    {
        "adapters": "lacuna.adapters.v1",
        "audit_rules": "lacuna.audit_rules.v1",
        "cost_models": "lacuna.cost_models.v1",
        "methods": "lacuna.methods.v1",
        "report_sections": "lacuna.report_sections.v1",
    }
)
_PROTOCOL_PATTERN = re.compile(r"^(?P<major>[1-9][0-9]*)\.(?P<minor>[0-9]+)$")


@dataclass(frozen=True, slots=True)
class PluginDescriptor:
    """Versioned metadata returned only after explicit plugin activation."""

    plugin_id: str
    protocol_version: str
    capabilities: tuple[str, ...]
    config_schema: Mapping[str, JsonValue] = field(default_factory=dict)
    method_versions: Mapping[str, int] = field(default_factory=dict)
    required_dependencies: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.plugin_id, str) or not self.plugin_id:
            raise MethodContractError("plugin_id must not be empty")
        if (
            not isinstance(self.protocol_version, str)
            or _PROTOCOL_PATTERN.fullmatch(self.protocol_version) is None
        ):
            raise MethodContractError("protocol_version must use '<major>.<minor>' notation")
        if (
            not isinstance(self.capabilities, tuple)
            or not self.capabilities
            or any(not isinstance(item, str) or not item for item in self.capabilities)
        ):
            raise MethodContractError("plugin capabilities must contain non-empty names")
        if len(set(self.capabilities)) != len(self.capabilities):
            raise MethodContractError("plugin capabilities must be unique")
        if not isinstance(self.config_schema, Mapping):
            raise MethodContractError("config_schema must be a JSON-compatible mapping")
        if not isinstance(self.method_versions, Mapping):
            raise MethodContractError("method_versions must be a name-to-version mapping")
        if any(
            not isinstance(name, str)
            or not name
            or isinstance(version, bool)
            or not isinstance(version, int)
            or version < 1
            for name, version in self.method_versions.items()
        ):
            raise MethodContractError("plugin method versions must be positive integers")
        if not isinstance(self.required_dependencies, tuple) or any(
            not isinstance(dependency, str) or not dependency
            for dependency in self.required_dependencies
        ):
            raise MethodContractError("required_dependencies must contain non-empty names")
        if len(set(self.required_dependencies)) != len(self.required_dependencies):
            raise MethodContractError("required_dependencies must be unique")
        # ResultMetadata performs strict JSON-value validation before we freeze
        # mappings against caller mutation.
        try:
            checked = ResultMetadata(
                method="plugins.descriptor_validation",
                parameters={"config_schema": self.config_schema},
            ).parameters["config_schema"]
        except (TypeError, ValueError) as error:
            raise MethodContractError("config_schema must be JSON-compatible") from error
        if not isinstance(checked, Mapping):  # pragma: no cover - validated above
            raise MethodContractError("config_schema must be a mapping")
        object.__setattr__(self, "config_schema", checked)
        object.__setattr__(
            self,
            "method_versions",
            MappingProxyType(dict(self.method_versions)),
        )


@dataclass(frozen=True, slots=True)
class PluginCandidate:
    """Installed entry-point metadata whose target has not been imported."""

    name: str
    group: str
    value: str
    distribution: str | None
    distribution_version: str | None
    _entry_point: metadata.EntryPoint = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class ActivatedPlugin:
    """A trusted plugin implementation activated by an explicit caller action."""

    candidate: PluginCandidate
    descriptor: PluginDescriptor
    implementation: object = field(repr=False, compare=False)
    evidence: AnalysisResult


def _groups(group: PluginGroup | None) -> tuple[str, ...]:
    if group is None:
        return tuple(ENTRY_POINT_GROUPS.values())
    try:
        return (ENTRY_POINT_GROUPS[group],)
    except KeyError as error:
        raise MethodContractError(f"unknown plugin group: {group!r}") from error


def _distribution(entry_point: metadata.EntryPoint) -> tuple[str | None, str | None]:
    distribution = getattr(entry_point, "dist", None)
    if distribution is None:
        return None, None
    return getattr(distribution, "name", None), getattr(distribution, "version", None)


def discover_plugins(*, group: PluginGroup | None = None) -> tuple[PluginCandidate, ...]:
    """Discover entry-point metadata without importing plugin target modules."""

    discovered: list[PluginCandidate] = []
    entry_points = metadata.entry_points()
    for entry_point_group in _groups(group):
        selected = entry_points.select(group=entry_point_group)
        for entry_point in selected:
            distribution, distribution_version = _distribution(entry_point)
            discovered.append(
                PluginCandidate(
                    name=entry_point.name,
                    group=entry_point.group,
                    value=entry_point.value,
                    distribution=distribution,
                    distribution_version=distribution_version,
                    _entry_point=entry_point,
                )
            )
    return tuple(
        sorted(
            discovered,
            key=lambda item: (
                item.group,
                item.name,
                item.distribution or "",
                item.value,
            ),
        )
    )


def select_plugin(
    name: str,
    *,
    group: PluginGroup,
    distribution: str | None = None,
) -> PluginCandidate:
    """Resolve one plugin, rejecting missing or ambiguous capability names."""

    if not name:
        raise MethodContractError("plugin name must not be empty")
    matches = [
        candidate
        for candidate in discover_plugins(group=group)
        if candidate.name == name
        and (distribution is None or candidate.distribution == distribution)
    ]
    if not matches:
        qualifier = f" from {distribution!r}" if distribution is not None else ""
        raise PluginError(f"plugin {name!r}{qualifier} is not installed in group {group!r}")
    if len(matches) > 1:
        providers = ", ".join(sorted(candidate.distribution or "unknown" for candidate in matches))
        raise PluginError(
            f"plugin name {name!r} is ambiguous in group {group!r}; choose a distribution: "
            f"{providers}"
        )
    return matches[0]


def activate_plugin(
    candidate: PluginCandidate,
    *,
    config: Mapping[str, JsonValue] | None = None,
    required_capability: str | None = None,
    protocol_major: int = 1,
) -> ActivatedPlugin:
    """Load and execute one explicitly selected trusted plugin factory.

    The entry point must resolve to a callable accepting one configuration
    mapping and returning an object with a ``descriptor`` attribute. Plugin
    code runs in-process with the caller's permissions; this API is not a
    sandbox or security boundary.
    """

    if not isinstance(candidate, PluginCandidate):
        raise MethodContractError("candidate must come from discover_plugins or select_plugin")
    if (
        isinstance(protocol_major, bool)
        or not isinstance(protocol_major, int)
        or protocol_major < 1
    ):
        raise MethodContractError("protocol_major must be a positive integer")
    if required_capability is not None and not required_capability:
        raise MethodContractError("required_capability must not be empty")
    resolved_config = dict(config or {})
    # Validate and freeze the public configuration evidence before executing code.
    try:
        checked_config = ResultMetadata(
            method="plugins.activation_config",
            parameters={"config": resolved_config},
        ).parameters["config"]
    except (TypeError, ValueError) as error:
        raise MethodContractError("config must be a JSON-compatible mapping") from error
    if not isinstance(checked_config, Mapping):  # pragma: no cover - construction invariant
        raise MethodContractError("config must be a JSON-compatible mapping")

    try:
        factory = candidate._entry_point.load()
    except Exception as error:
        raise PluginError(
            f"failed to import plugin {candidate.name!r} from {candidate.value!r}"
        ) from error
    if not callable(factory):
        raise PluginError("plugin entry point must resolve to a callable factory")
    try:
        implementation = factory(checked_config)
    except Exception as error:
        raise PluginError(f"plugin factory {candidate.name!r} failed during activation") from error
    descriptor = getattr(implementation, "descriptor", None)
    if not isinstance(descriptor, PluginDescriptor):
        raise PluginError("activated plugin must expose a PluginDescriptor as .descriptor")
    if descriptor.plugin_id != candidate.name:
        raise PluginError(
            f"plugin descriptor ID {descriptor.plugin_id!r} does not match entry-point name "
            f"{candidate.name!r}"
        )
    match = _PROTOCOL_PATTERN.fullmatch(descriptor.protocol_version)
    if match is None:  # pragma: no cover - PluginDescriptor validates this
        raise PluginError("plugin protocol version is malformed")
    observed_major = int(match.group("major"))
    if observed_major != protocol_major:
        raise PluginError(
            f"plugin protocol major {observed_major} is incompatible with required major "
            f"{protocol_major}"
        )
    if required_capability is not None and required_capability not in descriptor.capabilities:
        raise PluginError(
            f"plugin {candidate.name!r} does not provide capability {required_capability!r}"
        )

    evidence = AnalysisResult(
        metadata=ResultMetadata(
            method="plugins.activate",
            method_version=1,
            parameters={
                "plugin_id": descriptor.plugin_id,
                "entry_point_group": candidate.group,
                "entry_point_value": candidate.value,
                "distribution": candidate.distribution,
                "distribution_version": candidate.distribution_version,
                "protocol_version": descriptor.protocol_version,
                "required_capability": required_capability,
                "capabilities": descriptor.capabilities,
                "method_versions": cast(Mapping[str, JsonValue], descriptor.method_versions),
                "required_dependencies": descriptor.required_dependencies,
                "config": checked_config,
                "trusted_in_process_code": True,
            },
        ),
        metrics={"capability_count": len(descriptor.capabilities)},
    )
    return ActivatedPlugin(
        candidate=candidate,
        descriptor=descriptor,
        implementation=implementation,
        evidence=evidence,
    )


__all__ = [
    "ENTRY_POINT_GROUPS",
    "ActivatedPlugin",
    "PluginCandidate",
    "PluginDescriptor",
    "PluginGroup",
    "activate_plugin",
    "discover_plugins",
    "select_plugin",
]
