from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import pytest

from lacuna.exceptions import MethodContractError, PluginError
from lacuna.plugins import (
    ENTRY_POINT_GROUPS,
    PluginDescriptor,
    activate_plugin,
    discover_plugins,
    select_plugin,
)


@dataclass
class _Distribution:
    name: str
    version: str


class _EntryPoint:
    def __init__(
        self,
        name: str,
        group: str,
        value: str,
        factory: object,
        distribution: str = "example-dist",
    ) -> None:
        self.name = name
        self.group = group
        self.value = value
        self.dist = _Distribution(distribution, "2.4.0")
        self.factory = factory
        self.loads = 0

    def load(self) -> object:
        self.loads += 1
        return self.factory


class _EntryPoints(tuple[_EntryPoint, ...]):
    def select(self, *, group: str) -> _EntryPoints:
        return _EntryPoints(item for item in self if item.group == group)


@dataclass
class _Plugin:
    descriptor: PluginDescriptor
    config: object


def _factory(config: object) -> _Plugin:
    return _Plugin(
        PluginDescriptor(
            plugin_id="example",
            protocol_version="1.2",
            capabilities=("adapter.vendor.example",),
            config_schema={"type": "object"},
            method_versions={"normalize": 1},
            required_dependencies=("example-sdk>=2",),
        ),
        config,
    )


def _install(monkeypatch: pytest.MonkeyPatch, *entries: _EntryPoint) -> None:
    monkeypatch.setattr("lacuna.plugins.metadata.entry_points", lambda: _EntryPoints(entries))


def test_discovery_reads_metadata_without_loading_plugin_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = _EntryPoint(
        "example", ENTRY_POINT_GROUPS["adapters"], "example_plugin:create", _factory
    )
    _install(monkeypatch, entry)

    candidates = discover_plugins(group="adapters")

    assert len(candidates) == 1
    assert candidates[0].distribution == "example-dist"
    assert entry.loads == 0
    assert discover_plugins(group="methods") == ()


def test_selection_rejects_conflicts_unless_distribution_is_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _EntryPoint("example", ENTRY_POINT_GROUPS["adapters"], "one:create", _factory, "one")
    second = _EntryPoint("example", ENTRY_POINT_GROUPS["adapters"], "two:create", _factory, "two")
    _install(monkeypatch, first, second)

    with pytest.raises(PluginError, match="ambiguous"):
        select_plugin("example", group="adapters")
    assert select_plugin("example", group="adapters", distribution="two").value == "two:create"
    with pytest.raises(PluginError, match="not installed"):
        select_plugin("missing", group="adapters")


def test_explicit_activation_negotiates_protocol_and_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = _EntryPoint("example", ENTRY_POINT_GROUPS["adapters"], "example:create", _factory)
    _install(monkeypatch, entry)
    candidate = select_plugin("example", group="adapters")

    activated = activate_plugin(
        candidate,
        config={"dataset": "fundamentals"},
        required_capability="adapter.vendor.example",
    )

    assert entry.loads == 1
    assert activated.descriptor.protocol_version == "1.2"
    assert cast(_Plugin, activated.implementation).config == {"dataset": "fundamentals"}
    assert activated.evidence.metadata.parameters["trusted_in_process_code"] is True


def test_activation_rejects_incompatible_or_misdeclared_plugins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = _EntryPoint("example", ENTRY_POINT_GROUPS["adapters"], "example:create", _factory)
    _install(monkeypatch, entry)
    candidate = select_plugin("example", group="adapters")

    with pytest.raises(PluginError, match="protocol major"):
        activate_plugin(candidate, protocol_major=2)
    with pytest.raises(PluginError, match="does not provide"):
        activate_plugin(candidate, required_capability="adapter.missing")

    entry.factory = lambda config: object()
    with pytest.raises(PluginError, match="PluginDescriptor"):
        activate_plugin(candidate)


def test_plugin_contract_validation_rejects_invalid_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(MethodContractError, match="protocol_version"):
        PluginDescriptor("example", "v1", ("capability",))
    with pytest.raises(MethodContractError, match="capabilities"):
        PluginDescriptor("example", "1.0", ())
    entry = _EntryPoint("example", ENTRY_POINT_GROUPS["adapters"], "example:create", _factory)
    _install(monkeypatch, entry)
    candidate = select_plugin("example", group="adapters")
    with pytest.raises(MethodContractError, match="protocol_major"):
        activate_plugin(candidate, protocol_major=0)
    with pytest.raises(MethodContractError, match="unknown plugin group"):
        discover_plugins(group="unknown")  # type: ignore[arg-type]
