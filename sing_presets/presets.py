"""Presets: the snapshot a user picks, expressed as facts plus capabilities.

This is the file a user edits. It holds no configuration content: a preset says which
device it is for and which capabilities to include, and the capabilities decide what
that means. Adding a device is a few lines here; adding a feature is a capability module.
Neither multiplies the other.

Shape of the document:

    defaults:
      facts: {log.level: info}
      capabilities: [logging, tun-inbound, ...]
    presets:
      desktop:
        facts: {device.tun_address: [...], device.mtu: 9000}
        capabilities_add: [ipv4-only]

A preset inherits `defaults`, overrides individual facts, and may add or remove
capabilities. The result is always a flat list, so there is never a chain of inheritance
to reconstruct when reading a build.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from .capability import REGISTRY, discover

PRESET_KEYS = frozenset(
    {
        "description",
        "extends",
        "facts",
        "capabilities",
        "capabilities_add",
        "capabilities_remove",
    }
)
DEFAULTS_KEYS = frozenset({"facts", "capabilities"})
TOP_KEYS = frozenset({"version", "defaults", "presets"})
#: The only document version this loader understands. Accepting any number would let a
#: document written for a future shape load under today's rules and be read wrongly.
SUPPORTED_VERSION = 1


class PresetError(Exception):
    """The preset document is malformed, or names something that does not exist."""


@dataclass(frozen=True)
class Preset:
    name: str
    facts: Mapping[str, Any] = field(default_factory=dict)
    capabilities: tuple[str, ...] = ()
    description: str = ""


@dataclass(frozen=True)
class PresetFile:
    presets: Mapping[str, Preset]
    defaults: Mapping[str, Any] = field(default_factory=dict)

    @property
    def names(self) -> list[str]:
        return sorted(self.presets)


def _require_mapping(value: Any, where: str) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise PresetError(f"{where} must be a mapping, got {type(value).__name__}")
    return value


def _validate_facts(raw: Mapping[str, Any], where: str) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or "." not in key:
            raise PresetError(f"{where}: fact {key!r} must be a dotted name such as device.mtu")
        facts[key] = value
    return facts


def _capability_list(raw: Any, where: str) -> list[str]:
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise PresetError(f"{where} must be a list of capability ids")
    # A repeated id contributes its fields twice, which shows up as duplicated rules in the
    # finished configuration rather than as an error anywhere downstream. It is almost
    # always a copy-paste while merging two presets.
    repeated = sorted({item for item in raw if raw.count(item) > 1})
    if repeated:
        raise PresetError(f"{where} lists {', '.join(repeated)} more than once")
    return list(raw)


def _check_known(ids: Iterable[str], where: str) -> None:
    unknown = sorted({item for item in ids if item not in REGISTRY})
    if unknown:
        known = ", ".join(sorted(REGISTRY)) or "(none registered)"
        raise PresetError(f"{where}: unknown capability {unknown}; known: {known}")


def load(path: Path | str) -> PresetFile:
    """Read and validate a preset document."""
    # Importing the library is what registers the capabilities, and validation below has
    # to compare against a populated registry rather than against an empty one.
    discover()
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    document = _require_mapping(document, "the preset document")
    extra = sorted(set(document) - TOP_KEYS)
    if extra:
        raise PresetError(f"unknown top-level keys: {extra}")
    version = document.get("version")
    if version is not None and version != SUPPORTED_VERSION:
        raise PresetError(
            f"unsupported document version {version!r}; this loader reads version "
            f"{SUPPORTED_VERSION}"
        )

    defaults = _require_mapping(document.get("defaults"), "defaults")
    extra = sorted(set(defaults) - DEFAULTS_KEYS)
    if extra:
        # Without this a misspelled `capabilites:` is an empty defaults section rather than
        # an error, and the build fails later for a reason that names nothing.
        raise PresetError(f"defaults: unknown keys {extra}")
    default_facts = _validate_facts(
        _require_mapping(defaults.get("facts"), "defaults.facts"), "defaults.facts"
    )
    default_capabilities = _capability_list(
        defaults.get("capabilities", []), "defaults.capabilities"
    )
    _check_known(default_capabilities, "defaults.capabilities")

    raw_presets = _require_mapping(document.get("presets"), "presets")
    if not raw_presets:
        raise PresetError("the preset document defines no presets")
    for name, body in raw_presets.items():
        if not isinstance(name, str) or not name:
            raise PresetError(f"preset names must be non-empty strings, got {name!r}")
        body = _require_mapping(body, f"presets.{name}")
        extra = sorted(set(body) - PRESET_KEYS)
        if extra:
            raise PresetError(f"presets.{name}: unknown keys {extra}")

    presets: dict[str, Preset] = {}
    resolving: list[str] = []

    def resolve(name: str) -> Preset:
        if name in presets:
            return presets[name]
        if name in resolving:
            chain = " -> ".join([*resolving, name])
            raise PresetError(f"preset inheritance loops: {chain}")
        if name not in raw_presets:
            raise PresetError(f"presets.{resolving[-1] if resolving else '?'} extends unknown preset {name!r}")

        body = _require_mapping(raw_presets[name], f"presets.{name}")
        where = f"presets.{name}"
        resolving.append(name)
        try:
            parent_name = body.get("extends")
            if parent_name is None:
                parent = Preset(name=name, facts=dict(default_facts),
                                capabilities=tuple(default_capabilities))
            elif isinstance(parent_name, str):
                parent = resolve(parent_name)
            else:
                raise PresetError(f"{where}.extends must be a preset name")

            facts = dict(parent.facts)
            facts.update(
                _validate_facts(
                    _require_mapping(body.get("facts"), f"{where}.facts"), f"{where}.facts"
                )
            )

            if "capabilities" in body:
                capabilities = _capability_list(body["capabilities"], f"{where}.capabilities")
            else:
                capabilities = list(parent.capabilities)
            for capability_id in _capability_list(
                body.get("capabilities_add", []), f"{where}.capabilities_add"
            ):
                if capability_id not in capabilities:
                    capabilities.append(capability_id)
            for capability_id in _capability_list(
                body.get("capabilities_remove", []), f"{where}.capabilities_remove"
            ):
                if capability_id in capabilities:
                    capabilities.remove(capability_id)
                else:
                    raise PresetError(
                        f"{where}: cannot remove {capability_id!r}, it is not in the preset"
                    )
            _check_known(capabilities, where)
        finally:
            resolving.pop()

        preset = Preset(
            name=name,
            facts=facts,
            capabilities=tuple(capabilities),
            description=str(body.get("description", "")),
        )
        presets[name] = preset
        return preset

    for name in raw_presets:
        resolve(name)

    return PresetFile(
        presets=presets,
        defaults={"facts": default_facts, "capabilities": default_capabilities},
    )
