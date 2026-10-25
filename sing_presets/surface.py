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
from pathlib import Path
from typing import Iterable

DEFAULT_SURFACE_PATH = Path(__file__).resolve().parent.parent / "schema" / "surface.json"

ORDERED_KINDS = frozenset({"seq", "seq_tagged"})
MAP_KINDS = frozenset({"map_tag"})
SCALAR_KINDS = frozenset({"scalar", "scalar_list"})
TAGGED_KINDS = MAP_KINDS | {"seq_tagged"}
# object_or_scalar covers fields that accept either a scalar or an inline object, such as
# http_client (a client tag, or options with a detour). It can be set as a whole and its
# object properties can also be written one at a time.
SETTABLE_KINDS = SCALAR_KINDS | {"object_or_scalar"}

_TAG_PLACEHOLDER = re.compile(r"\{[^{}]*\}")


class SurfaceError(Exception):
    """A path was used in a way the field surface does not allow."""


@dataclass(frozen=True)
class Slot:
    path: str
    kind: str
    enum: tuple = ()
    reference: str | None = None
    variants: tuple = ()
    deprecated: bool = False

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
    def load(cls, path: Path | str = DEFAULT_SURFACE_PATH) -> "Surface":
        return cls._load_cached(Path(path))

    @classmethod
    @lru_cache(maxsize=4)
    def _load_cached(cls, path: Path) -> "Surface":
        raw = json.loads(path.read_text(encoding="utf-8"))
        slots: dict[str, Slot] = {}
        for key, entry in (raw.get("slots") or {}).items():
            slots[key] = Slot(
                path=key,
                kind=entry["kind"],
                enum=tuple(entry.get("enum") or ()),
                reference=entry.get("reference"),
                variants=tuple(entry.get("variants") or ()),
                deprecated=bool(entry.get("deprecated")),
            )
        return cls(slots, raw.get("source") or {})

    def get(self, path: str) -> Slot | None:
        return self._slots.get(normalize(path))

    def require(self, path: str, allowed: Iterable[str]) -> Slot:
        """Fetch a slot and check its kind, so writing outside it fails loudly."""
        slot = self.get(path)
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

    def top_level(self) -> list[str]:
        return list(self.source.get("top_level") or [])

    def check_config(self, config: object) -> list[str]:
        """Report every path in a built configuration that is absent from the surface.

        This catches misspelled or invented field names, which would otherwise produce a
        configuration that only fails inside sing-box. Run it in CI after every build.
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
                for key, value in node.items():
                    walk(value, f"{path}.{key}" if path else key, depth + 1)
            elif isinstance(node, list):
                # Element notation follows the collection's slot kind, matching what
                # tools/gen_surface.py emits: tagged collections use {tag}, others use [].
                suffix = "{tag}" if slot is not None and slot.kind in TAGGED_KINDS else "[]"
                for item in node:
                    walk(item, f"{path}{suffix}", depth + 1)

        walk(config, "", 0)
        return sorted(set(unknown))

    @property
    def binary_version(self) -> str | None:
        return self.source.get("binary_version")

    @property
    def schema_file(self) -> str | None:
        return self.source.get("schema_file")

    def __len__(self) -> int:
        return len(self._slots)
