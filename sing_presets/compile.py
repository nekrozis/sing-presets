"""Compile one preset into a configuration, and refuse to emit a broken one.

The compile step is where the pieces are put together, so it is also the only place that
can guarantee the result is coherent: contributions that were evaluated without a
conflict, fields that exist in the field surface, references that point at something real,
and no collection left empty.

Nothing here knows about sing-box field names. Anything that does is either a capability
(what to write) or the surface (what may be written).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from . import capability as cap
from .facts import Facts
from .ir import Builder, Contribution, Report, compile_config
from .presets import Preset
from .surface import Surface

#: Capability that turns the subscription's nodes into outbounds. Added automatically
#: when nodes are supplied, because a preset document has no business naming it.
NODES_CAPABILITY = "subscription-nodes"


class CompileError(Exception):
    """The preset cannot produce a configuration worth shipping."""


@dataclass(frozen=True)
class Build:
    preset: str
    facts: Facts
    capabilities: tuple[str, ...]
    config: dict
    report: Report
    contributions: tuple[Contribution, ...] = ()

    def summary(self) -> str:
        return (
            f"{self.preset}: {self.report.contributions} contributions from "
            f"{len(self.capabilities)} capabilities"
        )


def _validate_nodes(nodes: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Reject node lists that would make sing-box refuse to start.

    The check that matters is duplicate tags: sing-box rejects a configuration with two
    outbounds sharing a tag, and a subscription is free to contain two entries with the
    same display name. Catching it here names the offending tag instead of leaving a
    startup error at the other end.
    """
    validated: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    for index, node in enumerate(nodes):
        if not isinstance(node, Mapping):
            raise CompileError(f"node #{index} is not an object: {node!r}")
        tag = node.get("tag")
        if not isinstance(tag, str) or not tag:
            raise CompileError(f"node #{index} has no tag: {dict(node)!r}")
        if tag in seen:
            raise CompileError(
                f"duplicate node tag {tag!r} (positions {seen[tag]} and {index}); "
                "rename one of them before building"
            )
        seen[tag] = index
        validated.append(dict(node))
    return validated


def _check_empty_lists(config: Mapping[str, Any]) -> list[str]:
    """Report collections that ended up empty.

    An empty list is almost always a capability that expected something else to fill it:
    an `urltest` group with no members is rejected by sing-box outright, and the same
    mistake elsewhere fails quietly. The path includes the tag when there is one, so the
    message names the member rather than its collection.
    """
    empty: list[str] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            tag = node.get("tag")
            if isinstance(tag, str) and path:
                path = f"{path}{{{tag}}}"
            for key, value in node.items():
                walk(value, f"{path}.{key}" if path else key)
        elif isinstance(node, list):
            if not node:
                empty.append(path)
                return
            for item in node:
                walk(item, path)

    walk(config, "")
    return sorted(set(empty))


def _check_dependencies(capabilities: Sequence[cap.Capability]) -> list[str]:
    """Report declared dependencies the preset does not include.

    Without this the failure surfaces much later as "no member with tag 'auto'", which
    says nothing about what to add to the preset.
    """
    present = {item.id for item in capabilities}
    problems: list[str] = []
    for item in capabilities:
        missing = sorted(set(item.depends_on) - present)
        if missing:
            problems.append(
                f"{item.id!r} depends on {', '.join(missing)}, "
                "which the preset does not include"
            )
    return problems


def compile_preset(
    surface: Surface,
    preset: Preset,
    nodes: Sequence[Mapping[str, Any]] = (),
) -> Build:
    """Compile a preset, raising CompileError on anything that would not ship."""
    capability_ids = list(preset.capabilities)
    facts_values = dict(preset.facts)
    if nodes:
        if NODES_CAPABILITY not in capability_ids:
            capability_ids.append(NODES_CAPABILITY)
        facts_values["subscription.nodes"] = _validate_nodes(nodes)

    capabilities = cap.build_registry(capability_ids)
    dependency_problems = _check_dependencies(capabilities)
    if dependency_problems:
        raise CompileError("; ".join(dependency_problems))
    ownership = cap.check_ownership(capabilities)
    if ownership:
        raise CompileError("; ".join(ownership))

    facts = Facts.of(**facts_values)
    contributions = [
        item for capability in capabilities for item in capability.contributions(facts)
    ]
    dependencies = cap.dependency_map(capabilities)

    trespass = cap.check_trespass(contributions, dependencies)
    if trespass:
        raise CompileError("; ".join(trespass))

    config, report = compile_config(surface, contributions)
    if report.conflicts:
        raise CompileError(
            "conflicting contributions: " + "; ".join(str(item) for item in report.conflicts)
        )

    unknown = surface.check_config(config)
    if unknown:
        raise CompileError(
            "the build uses paths outside the field surface: " + ", ".join(unknown)
        )

    dangling = surface.check_references(config)
    if dangling:
        raise CompileError("dangling references: " + "; ".join(dangling))

    empty = _check_empty_lists(config)
    if empty:
        raise CompileError(
            "collections left empty (a preset is probably missing a capability, or the "
            "subscription returned nothing): " + ", ".join(empty)
        )

    return Build(
        preset=preset.name,
        facts=facts,
        capabilities=tuple(capability_ids),
        config=config,
        report=report,
        contributions=tuple(contributions),
    )


def compile_all(
    surface: Surface,
    presets: Iterable[Preset],
    nodes: Sequence[Mapping[str, Any]] = (),
) -> list[Build]:
    """Compile every preset, collecting every failure before raising.

    One at a time would stop at the first bad preset; a build that reports all of them is
    what someone fixing a preset document actually needs.
    """
    builds: list[Build] = []
    problems: list[str] = []
    for preset in presets:
        try:
            builds.append(compile_preset(surface, preset, nodes))
        except (CompileError, ValueError) as error:
            problems.append(f"{preset.name}: {error}")
    if problems:
        raise CompileError("\n".join(problems))
    return builds


def audit(surface: Surface, build: Build) -> list[str]:
    """Run the checks that are too slow for every build, for CI to run deliberately.

    Compiling is cheap; the isolation check rebuilds the configuration once per
    capability. A build therefore ships without it, and CI runs it so a newly added
    capability that quietly depends on another one is caught.
    """
    if not build.contributions:
        return []
    capabilities = cap.build_registry(build.capabilities)
    dependencies = cap.dependency_map(capabilities)
    builder = Builder(surface)
    problems = cap.check_trespass(build.contributions, dependencies)
    return problems + builder.verify_isolation(build.contributions, dependencies)
