"""Capabilities: the orthogonal units a preset is composed of.

A capability is a code unit, not a YAML fragment. That distinction is the whole point:
a fragment describes the shape of a finished configuration, so supporting "with and
without public IPv6" forces you to write both results out. A code unit carries the
conditional logic inside it, so one fact driving three fields is written once and the
number of combinations never changes the amount of code.

Subclasses register themselves automatically through `__init_subclass__`. This is
stronger than the reference clients, which keep a hand-maintained type table plus a
catch-all `else -> error(...)` that only fires at runtime. Here a capability that exists
is registered, so "forgot to register it" cannot happen.

The three criteria a capability must satisfy, and where they are enforced:

  1. it is one intent -- a group of fields that are always decided together
     (design constraint, not machine-checkable)
  2. independently switchable, leaving no residue -- ir.Builder.verify_isolation
  3. it does not touch fields another capability owns -- check_ownership / check_trespass
"""

from __future__ import annotations

import dataclasses
import importlib
import pkgutil
from typing import Any, Iterable, Mapping

from .facts import Facts, FactsError
from .ir import Anchor, Contribution, Entry, Member, Position, Setting

REGISTRY: dict[str, type["Capability"]] = {}


class CapabilityError(Exception):
    """A capability is malformed, duplicated, or misused."""


def _stamp(contribution: Contribution, owner: str) -> Contribution:
    """Stamp the owning capability onto a contribution so every field is traceable."""
    if contribution.owner == owner:
        return contribution
    return dataclasses.replace(contribution, owner=owner)


class Capability:
    #: unique identifier, also used as the contribution owner and in reports
    id: str = ""
    #: fact keys this capability reads; a preset missing one fails loudly
    requires: tuple[str, ...] = ()
    #: addresses this capability claims exclusively, e.g. "outbounds{proxy}"
    owns: tuple[str, ...] = ()
    #: capabilities this one needs, so the dependency is explicit rather than hidden
    depends_on: tuple[str, ...] = ()
    #: set on intermediate bases so they do not register
    abstract: bool = False

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if cls.abstract or not cls.id:
            return
        existing = REGISTRY.get(cls.id)
        if existing is not None and existing is not cls:
            raise CapabilityError(
                f"duplicate capability id {cls.id!r}: "
                f"{existing.__module__}.{existing.__name__} and "
                f"{cls.__module__}.{cls.__name__}"
            )
        REGISTRY[cls.id] = cls

    # -------------------------------------------------------------- authoring

    def contribute(self, facts: Facts) -> Iterable[Contribution]:
        raise NotImplementedError

    def contributions(self, facts: Facts) -> list[Contribution]:
        """Validate the required facts, run contribute(), and stamp the owner."""
        missing = facts.check_supported(self.requires)
        if missing:
            raise FactsError(f"capability {self.id!r} needs undeclared facts: {missing}")
        return [_stamp(item, self.id) for item in self.contribute(facts)]

    # small helpers so capability bodies stay readable
    def member(
        self,
        collection: str,
        tag: str,
        body: Any = None,
        **fields: Any,
    ) -> Member:
        """Build a member. The body may be given as a mapping, as keywords, or both."""
        merged: dict[str, Any] = dict(body) if body else {}
        merged.update(fields)
        return Member(collection=collection, tag=tag, body=merged)

    def entry(self, path: str, value: Any, position: Position | None = None) -> Entry:
        return Entry(path=path, value=value, position=position or Position.last())

    def setting(
        self, path: str, value: Any, priority: int = 0, override: bool = False
    ) -> Setting:
        return Setting(path=path, value=value, priority=priority, override=override)

    def anchor(self, path: str, name: str, rank: int) -> Anchor:
        return Anchor(path=path, name=name, rank=rank)

    def __repr__(self) -> str:
        return f"<{type(self).__name__} id={self.id!r}>"


def address_of(contribution: Contribution) -> str:
    """The concrete address a contribution writes to."""
    if isinstance(contribution, Member):
        return f"{contribution.collection}{{{contribution.tag}}}"
    return contribution.path


def discover(package: str = "sing_presets.capabilities") -> list[str]:
    """Import every module in a package so its capabilities register themselves.

    Without this, a module nobody imports would register nothing, and there is no
    compiler to catch it. Importing the package once is enough and is idempotent.
    """
    imported: list[str] = []
    try:
        root = importlib.import_module(package)
    except ModuleNotFoundError:
        return imported
    for module in pkgutil.iter_modules(root.__path__):
        if module.name.startswith("_"):
            continue
        importlib.import_module(f"{package}.{module.name}")
        imported.append(module.name)
    return sorted(imported)


def build_registry(ids: Iterable[str]) -> list[Capability]:
    """Instantiate the named capabilities, in the order given."""
    result: list[Capability] = []
    for capability_id in ids:
        cls = REGISTRY.get(capability_id)
        if cls is None:
            known = ", ".join(sorted(REGISTRY)) or "(none)"
            raise CapabilityError(f"unknown capability {capability_id!r}; known: {known}")
        result.append(cls())
    return result


def dependency_map(capabilities: Iterable[Capability]) -> dict[str, set[str]]:
    """Build the dependent -> dependencies map the isolation and trespass checks accept."""
    return {
        capability.id: set(capability.depends_on)
        for capability in capabilities
        if capability.depends_on
    }


def check_ownership(capabilities: Iterable[Capability]) -> list[str]:
    """Report addresses claimed by more than one capability (criterion 3)."""
    claims: dict[str, str] = {}
    problems: list[str] = []
    for capability in capabilities:
        for address in capability.owns:
            owner = claims.get(address)
            if owner is not None and owner != capability.id:
                problems.append(f"{address} is claimed by both {owner!r} and {capability.id!r}")
            claims[address] = capability.id
    return problems


def check_trespass(
    contributions: Iterable[Contribution],
    declared_dependencies: Mapping[str, Iterable[str]] | None = None,
) -> list[str]:
    """Report contributions that write inside an address owned by someone else.

    Writing inside another owner's member is allowed when the writer declares that it
    depends on the owner, because then the coupling is explicit instead of accidental.
    """
    declared = {
        owner: set(dependencies) for owner, dependencies in (declared_dependencies or {}).items()
    }
    items = list(contributions)
    claims: dict[str, str] = {}
    for item in items:
        if item.owner and isinstance(item, Member):
            claims.setdefault(address_of(item), item.owner)
    problems: list[str] = []
    for item in items:
        address = address_of(item)
        allowed = declared.get(item.owner, set())
        for claimed, owner in claims.items():
            if owner == item.owner or owner in allowed:
                continue
            if address == claimed or address.startswith(claimed + "."):
                problems.append(
                    f"{item.owner or '(anonymous)'} writes to {address}, which is inside "
                    f"{claimed} owned by {owner}"
                )
                break
    return problems
