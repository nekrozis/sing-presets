"""The field surface: the only set of objects a capability may produce.

The data is generated from `sing-box schema` by tools/gen_surface.py and regenerated
wholesale when targeting a newer sing-box release. This module only queries it; it holds
no knowledge about sing-box itself, so nothing here drifts.

Slot kinds (they decide the merge algebra implemented in ir.py):

    map_tag       elements carry a tag that can be referenced elsewhere -> merged by tag
    seq_tagged    elements carry a tag that nothing references -> ordered, tag = anchor
    seq           ordered array -> positioned by anchors
    object        plain object container
    scalar        scalar value
    scalar_list   single value or list
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Iterable

#: Where the generated field surface lives inside the package: an installed copy carries it,
#: and a zipapp can only read what is inside the archive. Regenerate it with
#: tools/gen_surface.py. Kept as two names rather than one `Path` because the archive branch
#: below walks entries, where a separator inside a single name is a character, not a break:
#: `Path("data") / "surface.json"` is `data\surface.json` on Windows, and no such entry exists.
SURFACE_DIRECTORY = "data"
SURFACE_FILENAME = "surface.json"


def load_surface_text() -> str:
    """The surface this code ships with, as text.

    Read from the file beside this module when there is one, and through the import machinery
    when there is not: inside a zipapp the package is an archive entry, so a path built from
    `__file__` names something that cannot be opened.
    """
    beside = Path(__file__).resolve().parent / SURFACE_DIRECTORY / SURFACE_FILENAME
    if beside.is_file():
        return beside.read_text(encoding="utf-8")
    return (
        files("sing_presets") / SURFACE_DIRECTORY / SURFACE_FILENAME
    ).read_text(encoding="utf-8")

ORDERED_KINDS = frozenset({"seq", "seq_tagged"})
MAP_KINDS = frozenset({"map_tag"})
SCALAR_KINDS = frozenset({"scalar", "scalar_list"})
TAGGED_KINDS = MAP_KINDS | {"seq_tagged"}
# object_or_scalar covers fields that accept either a scalar or an inline object, such as
# http_client (a client tag, or options with a detour). It can be set as a whole and its
# object properties can also be written one at a time.
SETTABLE_KINDS = SCALAR_KINDS | {"object_or_scalar"}

_TAG_PLACEHOLDER = re.compile(r"\{[^{}]*\}")

#: Where a tag of each reference kind must be defined. Derived from the `x-tag-reference`
#: markers tools/gen_surface.py records, so a reference kind that sing-box adds shows up
#: as "unmapped" instead of silently going unchecked.
REFERENCE_COLLECTIONS = {
    "outbound": ("outbounds", "endpoints"),
    "inbound": ("inbounds",),
    "dns_server": ("dns.servers",),
    "rule_set": ("route.rule_set",),
    "network_namespace": ("network_namespaces",),
    "certificate_provider": ("certificate_providers",),
    "http_client": ("http_clients",),
}


class SurfaceError(Exception):
    """A path was used in a way the field surface does not allow."""


@dataclass(frozen=True)
class Slot:
    path: str
    kind: str
    #: values the schema names for this field, when it names them. Empty means the field
    #: is free-form (a URL, a number of bytes) and only its presence can be checked.
    enum: tuple = ()
    reference: str | None = None
    #: the object accepts properties the schema does not name, e.g. an HTTP header map.
    #: Without this the build would reject `headers.Host`, which is a legitimate field.
    open: bool = False

    @property
    def is_map(self) -> bool:
        return self.kind in MAP_KINDS

    @property
    def is_ordered(self) -> bool:
        return self.kind in ORDERED_KINDS

    @property
    def is_scalar(self) -> bool:
        return self.kind in SCALAR_KINDS


def normalize(path: str) -> str:
    """Fold a concrete address into the placeholder form: outbounds{proxy} -> outbounds{tag}."""
    return _TAG_PLACEHOLDER.sub("{tag}", path)


class Surface:
    def __init__(self, slots: dict[str, Slot], source: dict) -> None:
        self._slots = slots
        self.source = source

    @classmethod
    def load(cls, path: Path | str | None = None) -> "Surface":
        """Load a surface from a file, or the one this code ships with when given no path."""
        text = (
            load_surface_text() if path is None else Path(path).read_text(encoding="utf-8")
        )
        return cls._parse_cached(text)

    @classmethod
    @lru_cache(maxsize=4)
    def _parse_cached(cls, text: str) -> "Surface":
        raw = json.loads(text)
        slots: dict[str, Slot] = {}
        for key, entry in (raw.get("slots") or {}).items():
            slots[key] = Slot(
                path=key,
                kind=entry["kind"],
                enum=tuple(entry.get("enum") or ()),
                reference=entry.get("reference"),
                open=bool(entry.get("open")),
            )
        return cls(slots, raw.get("source") or {})

    def get(self, path: str) -> Slot | None:
        return self._slots.get(normalize(path))

    def slot_for(self, path: str) -> Slot | None:
        """The slot a path denotes, including a key inside an open object.

        An open object's keys are data rather than fields - an HTTP header name, a server
        name to fall back for - so neither the schema nor this surface can list them, and
        `get` answers nothing for them. They are still addresses a capability may write:
        the key is free-form, the value is a plain scalar, which is the only shape an
        override of one can take. A key of a closed object stays unknown, because there the
        schema has said the field does not exist.
        """
        slot = self.get(path)
        if slot is not None:
            return slot
        parent, _, key = path.rpartition(".")
        if not key:
            return None
        parent_slot = self.get(parent)
        if parent_slot is None or not parent_slot.open:
            return None
        return Slot(path=path, kind="scalar", open=True)

    def require(self, path: str, allowed: Iterable[str]) -> Slot:
        """Fetch a slot and check its kind, so writing outside it fails loudly."""
        slot = self.slot_for(path)
        if slot is None:
            raise SurfaceError(f"path is not part of the field surface: {path}")
        allowed = frozenset(allowed)
        if slot.kind not in allowed:
            raise SurfaceError(
                f"{path} has slot kind {slot.kind}, but is used as {sorted(allowed)}"
            )
        return slot

    def kind_of(self, path: str) -> str | None:
        slot = self.get(path)
        return slot.kind if slot else None

    def fields_below(self, path: str) -> list[str]:
        """The field names directly below a path, without their sub-fields or elements."""
        prefix = normalize(path).rstrip(".") + "."
        names: set[str] = set()
        for key in self._slots:
            if key.startswith(prefix):
                head = key[len(prefix) :].split(".")[0].split("[")[0]
                if head:
                    names.add(head)
        return sorted(names)

    def top_level(self) -> list[str]:
        return list(self.source.get("top_level") or [])

    def check_config(self, config: object) -> list[str]:
        """Report every path in a built configuration that is absent from the surface.

        This catches misspelled or invented field names, which would otherwise produce a
        configuration that only fails inside sing-box. Run it in CI after every build.

        An open object is exempt: it accepts properties the schema does not name, because
        its keys are data - HTTP header names, SNI values to fall back for - and not fields.
        """
        unknown: list[str] = []

        def walk(node: object, path: str, depth: int) -> None:
            if depth > 32:
                return
            slot = self.get(path) if path else None
            if path and slot is None:
                unknown.append(path)
                return
            if isinstance(node, dict):
                free_form = slot is not None and slot.open
                for key, value in node.items():
                    child = f"{path}.{key}" if path else key
                    if free_form and self.get(child) is None:
                        continue
                    walk(value, child, depth + 1)
            elif isinstance(node, list):
                if slot is not None and slot.kind == "scalar_list":
                    # The field is the list, so its elements are values and there is no
                    # field below them to look up. The surface does record `<path>[]`, but
                    # only as deep as the generator walks, and a rule nested inside a rule
                    # list is already past that: deriving the element here keeps a
                    # legitimate list from being reported as an invented path.
                    for item in node:
                        if isinstance(item, (dict, list)):
                            walk(item, f"{path}[]", depth + 1)
                    return
                # Element notation follows the collection's slot kind, matching what
                # tools/gen_surface.py emits: tagged collections use {tag}, others use [].
                suffix = "{tag}" if slot is not None and slot.kind in TAGGED_KINDS else "[]"
                for item in node:
                    walk(item, f"{path}{suffix}", depth + 1)

        walk(config, "", 0)
        return sorted(set(unknown))

    def check_values(self, config: object) -> list[str]:
        """Report values the schema does not list for their field.

        `check_config` proves the path exists; this proves the value is one sing-box names.
        Without it a typo like `log.level: verbose` or a protocol that the binary does not
        build in compiles cleanly and only fails on the device - and with `--no-verify`, or
        in CI without a binary, nothing catches it at all.

        Only enumerated fields are checked. A field the schema leaves open (a server name, a
        byte count) cannot be judged here, and guessing would reject correct builds.
        """
        problems: list[str] = []

        def check(path: str, value: object) -> None:
            slot = self.get(path)
            if slot is None or not slot.enum:
                return
            if isinstance(value, (dict, list)):
                return
            try:
                allowed = value in slot.enum
            except TypeError:  # pragma: no cover - unhashable never compares unequal
                allowed = False
            if not allowed:
                problems.append(
                    f"{path}: {value!r} is not one of {', '.join(repr(v) for v in slot.enum)}"
                )

        def walk(node: object, path: str, depth: int) -> None:
            if depth > 32:
                return
            slot = self.get(path) if path else None
            if isinstance(node, dict):
                for key, value in node.items():
                    walk(value, f"{path}.{key}" if path else key, depth + 1)
                return
            if isinstance(node, list):
                if slot is not None and slot.kind == "scalar_list":
                    # The list is the field, so each element is a candidate value; an object
                    # element is one alternative shape and is walked as usual.
                    for item in node:
                        if isinstance(item, (dict, list)):
                            walk(item, f"{path}[]", depth + 1)
                        else:
                            check(path, item)
                    return
                suffix = "{tag}" if slot is not None and slot.kind in TAGGED_KINDS else "[]"
                for item in node:
                    walk(item, f"{path}{suffix}", depth + 1)
                return
            check(path, node)

        walk(config, "", 0)
        return sorted(set(problems))

    def check_references(self, config: object) -> list[str]:
        """Report references to tags that the configuration never defines.

        Every field sing-box marks `reference:"..."` points at a tag defined elsewhere, so
        a dangling one is a configuration that only fails at startup: an empty
        subscription leaving a selector with nothing to point at, a rule naming a rule set
        the preset forgot to include, a resolver detour to an outbound that is not there.

        Values that are objects rather than strings define their target inline and are
        left alone.
        """
        defined: dict[str, set[str]] = {}

        def tags_at(path: str) -> set[str]:
            if path in defined:
                return defined[path]
            node: object = config
            for segment in path.split("."):
                node = node.get(segment) if isinstance(node, dict) else None
            tags = {
                item["tag"]
                for item in (node if isinstance(node, list) else [])
                if isinstance(item, dict) and isinstance(item.get("tag"), str)
            }
            defined[path] = tags
            return tags

        dangling: list[str] = []

        def check(path: str, slot: Slot | None, value: object) -> None:
            if slot is None or slot.reference is None or not isinstance(value, str):
                return
            if value == "":
                return
            collections = REFERENCE_COLLECTIONS.get(slot.reference)
            if collections is None:
                dangling.append(f"{path}: reference kind {slot.reference!r} is not mapped")
                return
            known: set[str] = set()
            for collection in collections:
                known |= tags_at(collection)
            if value not in known:
                missing = " or ".join(collections)
                dangling.append(f"{path}: {value!r} is not defined in {missing}")

        def walk(node: object, path: str, depth: int) -> None:
            if depth > 32:
                return
            slot = self.get(path) if path else None
            if isinstance(node, dict):
                for key, value in node.items():
                    walk(value, f"{path}.{key}" if path else key, depth + 1)
                return
            if isinstance(node, list):
                if slot is not None and slot.kind == "scalar_list":
                    # A list-valued reference such as `rule_set`: each element names a tag,
                    # and the field is what carries the reference kind.
                    for item in node:
                        check(path, slot, item)
                    return
                suffix = "{tag}" if slot is not None and slot.kind in TAGGED_KINDS else "[]"
                for item in node:
                    walk(item, f"{path}{suffix}", depth + 1)
                return
            check(path, slot, node)

        walk(config, "", 0)
        return sorted(set(dangling))

    @property
    def binary_version(self) -> str | None:
        return self.source.get("binary_version")
    @property
    def schema_file(self) -> str | None:
        return self.source.get("schema_file")

    def __len__(self) -> int:
        return len(self._slots)
