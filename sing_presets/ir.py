"""The IR and the merge algebra for the three slot families.

A capability never assembles JSON directly. It emits *contributions*:

    Member   put a tagged member into a map_tag collection (merged by tag)
    Entry    insert an item into an ordered collection (positioned by anchors)
    Setting  set a scalar (conflicts resolved by explicit priority)
    Anchor   declare a named point in an ordered collection for others to target

Why this exists: upstream sing-box merging operates on values and is fill-in only -
the first loaded file wins for scalars, arrays are pure appends, and elements sharing a
tag are not merged. That loses "which rule is this, and where does it belong". Expressing
intent as contributions and evaluating them against the field surface keeps that
information intact, and it makes subtraction possible: a capability that is not in the
list simply contributes nothing, so removing fields never needs a value-level delete.

Ordering uses integer "bands" plus insertion order rather than floating point epsilon:

    first       -> (MIN,  0)
    before(a)   -> (r_a, -1)
    at(n)       -> (n,    0)
    after(a)    -> (r_a, +1)
    last        -> (MAX,  0)

Items in the same band keep insertion order, so results are deterministic.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from collections import Counter
from typing import Any, Iterable, Mapping

from .surface import MAP_KINDS, ORDERED_KINDS, SETTABLE_KINDS, Surface

ANCHOR_MIN = -(10**9)
ANCHOR_MAX = 10**9

# Slots an Entry may target: ordered collections, plus scalar_list because sing-box
# accepts either a single value or a list there, and appending is the natural operation.
INSERTABLE_KINDS = ORDERED_KINDS | {"scalar_list"}


class IRError(Exception):
    """A contribution cannot be placed, or violates the slot semantics."""


@dataclass(frozen=True)
class Position:
    kind: str = "last"
    rank: int = 0
    anchor: str | None = None

    @staticmethod
    def first() -> "Position":
        return Position("first")

    @staticmethod
    def last() -> "Position":
        return Position("last")

    @staticmethod
    def at(rank: int) -> "Position":
        return Position("at", rank=rank)

    @staticmethod
    def before(anchor: str) -> "Position":
        return Position("before", anchor=anchor)

    @staticmethod
    def after(anchor: str) -> "Position":
        return Position("after", anchor=anchor)

    def band(self, anchors: Mapping[str, int], path: str) -> tuple[int, int]:
        if self.kind == "first":
            return (ANCHOR_MIN, 0)
        if self.kind == "last":
            return (ANCHOR_MAX, 0)
        if self.kind == "at":
            return (self.rank, 0)
        if self.anchor is None or self.anchor not in anchors:
            raise IRError(f"{path} targets an undeclared anchor: {self.anchor!r}")
        return (anchors[self.anchor], -1 if self.kind == "before" else 1)


@dataclass(frozen=True)
class Member:
    """A tagged member of a map_tag collection. The tag is the key, so body excludes it."""

    collection: str
    tag: str
    body: Mapping[str, Any] = field(default_factory=dict)
    owner: str = ""

    @property
    def path(self) -> str:
        return f"{self.collection}{{{self.tag}}}"


@dataclass(frozen=True)
class Entry:
    """An item inserted into an ordered collection."""

    path: str
    value: Any
    position: Position = field(default_factory=Position.last)
    owner: str = ""


@dataclass(frozen=True)
class Setting:
    """A scalar. The highest priority wins; equal priority with different values conflicts."""

    path: str
    value: Any
    priority: int = 0
    owner: str = ""


@dataclass(frozen=True)
class Anchor:
    """A named point declared in an ordered collection."""

    path: str
    name: str
    rank: int
    owner: str = ""


Contribution = Member | Entry | Setting | Anchor


@dataclass(frozen=True)
class Conflict:
    path: str
    existing_owner: str
    incoming_owner: str
    existing_value: Any
    incoming_value: Any

    def __str__(self) -> str:
        return (
            f"{self.path}: [{self.existing_owner}] {self.existing_value!r} conflicts with "
            f"[{self.incoming_owner}] {self.incoming_value!r}"
        )


@dataclass
class Report:
    """Who contributed what, and what conflicted. Used for diffing and troubleshooting."""

    contributions: int = 0
    per_owner: dict[str, list[str]] = field(default_factory=dict)
    conflicts: list[Conflict] = field(default_factory=list)

    def paths_of(self, owner: str) -> list[str]:
        return list(self.per_owner.get(owner, ()))

    @property
    def ok(self) -> bool:
        return not self.conflicts


@dataclass
class _MergedMember:
    tag: str
    body: dict
    owner: str


def _parse_segment(segment: str) -> tuple[str, str | None]:
    """'outbounds{proxy}' -> ('outbounds', 'proxy')"""
    if "{" in segment and segment.endswith("}"):
        name, _, rest = segment.partition("{")
        return name, rest[:-1]
    return segment, None


def _find_member(items: Iterable[dict], tag: str) -> dict:
    for item in items:
        if item.get("tag") == tag:
            return item
    raise IRError(f"no member with tag {tag!r}")


def flatten(config: Mapping[str, Any], prefix: str = "") -> dict[str, Any]:
    """Flatten a config into leaf paths, so two builds can be diffed precisely."""
    leaves: dict[str, Any] = {}
    for key, value in config.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            leaves.update(flatten(value, path))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                index_path = f"{path}[{index}]"
                if isinstance(item, dict):
                    leaves.update(flatten(item, index_path))
                else:
                    leaves[index_path] = item
        else:
            leaves[path] = value
    return leaves


def leaf_multiset(config: Mapping[str, Any]) -> dict[str, Counter[str]]:
    """Collect leaves by path without positional identity, for comparing two builds.

    `flatten` numbers list items by index, which is right for reading a config but wrong
    for comparing two of them: dropping one rule shifts every later index, so every
    neighbour looks modified. Ordered lists here have no identity of their own (that is
    the whole reason `Seq[anchor]` exists), so their members are collected as a multiset
    of values under the list's path. Tagged members are keyed by tag, since they do carry
    an identity.

    The result is path -> Counter of serialised values, so a path that holds two equal
    rules still compares correctly.
    """
    collected: dict[str, Counter[str]] = {}
    _collect(config, "", collected)
    return collected


def _collect(node: Any, path: str, collected: dict[str, Counter[str]]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            _collect(value, f"{path}.{key}" if path else key, collected)
    elif isinstance(node, list):
        for item in node:
            if isinstance(item, dict) and "tag" in item:
                _collect(item, f"{path}{{{item['tag']}}}", collected)
            elif isinstance(item, dict):
                _collect(item, f"{path}[]", collected)
            else:
                _add(path, item, collected)
    else:
        _add(path, node, collected)


def _add(path: str, value: Any, collected: dict[str, Counter[str]]) -> None:
    collected.setdefault(path, Counter())[json.dumps(value, sort_keys=True)] += 1


def tokens_of(contribution: Contribution) -> dict[str, Counter[str]]:
    """The leaves a single contribution writes, encoded the same way as leaf_multiset.

    Used to tell "this owner took its own field away" from "disabling it changed someone
    else's field", which a whole-config diff cannot distinguish.
    """
    collected: dict[str, Counter[str]] = {}
    if isinstance(contribution, Member):
        body = dict(contribution.body)
        body["tag"] = contribution.tag
        _collect(body, contribution.path, collected)
    elif isinstance(contribution, Entry):
        if isinstance(contribution.value, dict):
            _collect(contribution.value, f"{contribution.path}[]", collected)
        else:
            _add(contribution.path, contribution.value, collected)
    elif isinstance(contribution, Setting):
        _add(contribution.path, contribution.value, collected)
    return collected


def _merge_tokens(
    parts: Iterable[Mapping[str, Counter[str]]],
) -> dict[str, Counter[str]]:
    merged: dict[str, Counter[str]] = {}
    for part in parts:
        for path, counts in part.items():
            merged.setdefault(path, Counter()).update(counts)
    return merged


def _describe(counts: Counter[str]) -> str:
    return ", ".join(f"{count}x{value}" for value, count in sorted(counts.items()))


class Builder:
    """Collects contributions and evaluates them into one configuration."""

    def __init__(self, surface: Surface) -> None:
        self.surface = surface
        self._members: dict[str, dict[str, _MergedMember]] = {}
        self._entries: dict[str, list[tuple[Position, int, Any, str]]] = {}
        self._settings: dict[str, tuple[int, int, Any, str]] = {}
        self._anchors: dict[str, dict[str, int]] = {}
        self._insertion = 0
        self.report = Report()

    # ------------------------------------------------------------- collection

    def add(self, contribution: Contribution) -> None:
        if isinstance(contribution, Member):
            self._add_member(contribution)
        elif isinstance(contribution, Entry):
            self._add_entry(contribution)
        elif isinstance(contribution, Setting):
            self._add_setting(contribution)
        elif isinstance(contribution, Anchor):
            self._add_anchor(contribution)
        else:  # pragma: no cover - defensive
            raise IRError(f"unknown contribution type: {type(contribution).__name__}")
        self.report.contributions += 1
        self.report.per_owner.setdefault(contribution.owner, []).append(contribution.path)

    def add_all(self, contributions: Iterable[Contribution]) -> None:
        for contribution in contributions:
            self.add(contribution)

    def _add_member(self, member: Member) -> None:
        self.surface.require(member.collection, MAP_KINDS)
        if not member.tag:
            raise IRError(f"member of {member.collection} has no tag")
        bucket = self._members.setdefault(member.collection, {})
        existing = bucket.get(member.tag)
        if existing is None:
            bucket[member.tag] = _MergedMember(
                tag=member.tag, body=dict(member.body), owner=member.owner
            )
            return
        self._merge_body(existing, dict(member.body), member.path, member.owner)

    def _merge_body(self, target: _MergedMember, incoming: dict, path: str, owner: str) -> None:
        """Merge by tag instead of duplicating the member, which sing-box would reject.

        Two capabilities may each want to touch the same member: one declares it, another
        extends it. Distinct keys merge; the same key with a different value is a conflict
        and is reported with both owners.
        """
        for key, value in incoming.items():
            if key not in target.body:
                target.body[key] = value
                continue
            current = target.body[key]
            if isinstance(current, dict) and isinstance(value, dict):
                nested = _MergedMember(tag=target.tag, body=current, owner=target.owner)
                self._merge_body(nested, value, f"{path}.{key}", owner)
                target.body[key] = nested.body
            elif current != value:
                self.report.conflicts.append(
                    Conflict(
                        path=f"{path}.{key}",
                        existing_owner=target.owner,
                        incoming_owner=owner,
                        existing_value=current,
                        incoming_value=value,
                    )
                )

    def _add_entry(self, entry: Entry) -> None:
        self.surface.require(entry.path, INSERTABLE_KINDS)
        self._insertion += 1
        self._entries.setdefault(entry.path, []).append(
            (entry.position, self._insertion, entry.value, entry.owner)
        )

    def _add_setting(self, setting: Setting) -> None:
        self.surface.require(setting.path, SETTABLE_KINDS)
        self._insertion += 1
        current = self._settings.get(setting.path)
        if current is None:
            self._settings[setting.path] = (
                setting.priority,
                self._insertion,
                setting.value,
                setting.owner,
            )
            return
        priority, _, value, owner = current
        if value == setting.value:
            return
        if setting.priority > priority:
            self._settings[setting.path] = (
                setting.priority,
                self._insertion,
                setting.value,
                setting.owner,
            )
            return
        if setting.priority < priority:
            # Outvoted, and not a conflict: the answer was never in doubt. Reporting one
            # would make the outcome depend on the order the capabilities are listed in,
            # since the same pair is accepted when the weak setting arrives first.
            return
        self.report.conflicts.append(
            Conflict(
                path=setting.path,
                existing_owner=owner,
                incoming_owner=setting.owner,
                existing_value=value,
                incoming_value=setting.value,
            )
        )

    def _add_anchor(self, anchor: Anchor) -> None:
        self.surface.require(anchor.path, INSERTABLE_KINDS)
        bucket = self._anchors.setdefault(anchor.path, {})
        if anchor.name in bucket and bucket[anchor.name] != anchor.rank:
            raise IRError(f"anchor {anchor.name!r} of {anchor.path} redeclared at another rank")
        bucket[anchor.name] = anchor.rank

    # ------------------------------------------------------------- evaluation

    def _resolved_seq(self, path: str, existing: Any) -> list[Any]:
        """Order a sequence, keeping whatever the member body already declared.

        A member body may seed a list (a selector's initial outbounds) while other owners
        append to the same list. Body items behave as rank 0: they sort ahead of same-rank
        entries and behind anything positioned earlier, and they are never dropped.
        """
        seed: list[tuple[Position, int, Any]] = []
        if isinstance(existing, list):
            seed = [
                (Position.at(0), index - len(existing), item)
                for index, item in enumerate(existing)
            ]
        anchors = self._anchors.get(path, {})
        combined = seed + self._entries.get(path, [])
        combined.sort(key=lambda item: (item[0].band(anchors, path), item[1]))
        return [item[2] for item in combined]

    def materialize(self) -> dict:
        config: dict[str, Any] = {}
        # Members first: nested paths such as outbounds{proxy}.outbounds need their
        # parent member to exist before they can be placed. Collections are addressed by
        # dotted path too, so dns.servers nests under dns rather than becoming a flat key.
        for collection in sorted(self._members):
            parent, name = self._container(collection, config)
            items = parent.setdefault(name, [])
            if not isinstance(items, list):
                raise IRError(f"{collection} is already occupied by a non-collection")
            for member in self._members[collection].values():
                body = dict(member.body)
                body["tag"] = member.tag
                items.append(body)
        for path in sorted(self._entries):
            parent, name = self._container(path, config)
            parent[name] = self._resolved_seq(path, parent.get(name))
        for path, (_, _, value, _) in sorted(self._settings.items()):
            parent, name = self._container(path, config)
            parent[name] = value
        return config

    def _container(self, path: str, config: dict) -> tuple[Any, str]:
        """Return (parent container, last segment name) for a concrete path.

        A missing collection or member means another capability was supposed to create it
        and did not, which is a dependency rather than a typo, so it is raised as IRError
        with an explanation instead of leaking a KeyError.
        """
        segments = path.split(".")
        node: Any = config
        for segment in segments[:-1]:
            name, tag = _parse_segment(segment)
            if tag is None:
                child = node.get(name)
                if child is None:
                    child = node.setdefault(name, {})
                elif not isinstance(child, dict):
                    raise IRError(f"{path}: {name!r} is already populated as a non-object")
                node = child
            else:
                items = node.get(name)
                if not isinstance(items, list):
                    raise IRError(
                        f"{path}: {name!r} has no members yet, so tag {tag!r} cannot be located"
                    )
                node = _find_member(items, tag)
        name, _ = _parse_segment(segments[-1])
        return node, name

    # ------------------------------------------------------------- criteria

    def verify_isolation(
        self,
        contributions: Iterable[Contribution],
        declared_dependencies: Mapping[str, Iterable[str]] | None = None,
    ) -> list[str]:
        """Check the "independently switchable, leaves no residue" criterion.

        For each owner, rebuild without its contributions and diff the *materialised*
        output, not the contribution list. Two failure modes matter:

          - the rebuild raises, meaning some other capability needed this one
          - leaves appear or change value, meaning this one was silently shadowing
            another's field

        Dependencies are legitimate when they are declared. `declared_dependencies` maps a
        dependent to the owners it needs, and a breakage explained by that map is not
        reported, so genuine hidden coupling still stands out.
        """
        declared: dict[str, set[str]] = {
            owner: set(dependencies)
            for owner, dependencies in (declared_dependencies or {}).items()
        }
        everything = list(contributions)
        owners = sorted({item.owner for item in everything if item.owner})
        full_config = compile_config(self.surface, everything)[0]
        full = leaf_multiset(full_config)
        # A contribution list is not required to be a whole configuration, so a dangling
        # reference may already be there. Only the ones disabling an owner introduces say
        # anything about that owner.
        baseline_dangling = set(self.surface.check_references(full_config))
        problems: list[str] = []

        for owner in owners:
            dependents = sorted(
                dependent for dependent, deps in declared.items() if owner in deps
            )
            without = [item for item in everything if item.owner != owner]
            try:
                reduced_config = compile_config(self.surface, without)[0]
            except IRError as error:
                if dependents:
                    continue  # declared dependency, not hidden coupling
                problems.append(
                    f"{owner}: rebuild fails once disabled, so others depend on it ({error})"
                )
                continue
            reduced = leaf_multiset(reduced_config)

            # A reference to a tag this owner defines is coupling too, and it survives the
            # rebuild because the referring field belongs to someone else: the value stays,
            # its target does not. Compiling a preset would still catch it, but as a
            # dangling reference rather than as "this capability is required".
            dangling = (
                []
                if dependents
                else [
                    problem
                    for problem in self.surface.check_references(reduced_config)
                    if problem not in baseline_dangling
                ]
            )
            if dangling:
                problems.append(
                    f"{owner}: disabling it leaves references to tags only it defines "
                    f"({'; '.join(dangling)}); the capability that writes them should "
                    "declare depends_on"
                )

            own = _merge_tokens(
                tokens_of(item) for item in everything if item.owner == owner
            )
            appeared: list[str] = []
            for path in sorted(set(reduced) - set(full)):
                appeared.append(path)
            rogue: list[str] = []
            for path in sorted(set(full) & set(reduced)):
                added = reduced[path] - full[path]
                if added:
                    appeared.append(f"{path} ({_describe(added)})")
                removed = full[path] - reduced[path]
                unexplained = removed - own.get(path, Counter())
                if unexplained:
                    rogue.append(f"{path} ({_describe(unexplained)})")

            if appeared:
                problems.append(f"{owner}: leaves appear once disabled: {appeared}")
            if rogue:
                problems.append(
                    f"{owner}: disabling it also removes values it never contributed: {rogue}"
                )
        return problems


def compile_config(surface: Surface, contributions: Iterable[Contribution]) -> tuple[dict, Report]:
    builder = Builder(surface)
    builder.add_all(contributions)
    return builder.materialize(), builder.report
