#!/usr/bin/env python3
"""Generate the sing-box "field surface" and slot classification from its JSON Schema.

The field surface is the only set of objects a capability is allowed to produce.
The slot type decides the merge algebra used by sing_presets.ir:

    map_tag       array whose elements carry a tag that can be referenced elsewhere.
                  Effectively a map: merged by tag, and a duplicate tag can never be
                  silently created. Order carries no meaning.
    seq_tagged    array whose elements carry a tag that nothing references. The tag is
                  only a label and may serve as an insertion anchor. Order still matters.
    seq           ordered array without tags. Order matters; positioned by anchors.
    object        plain object container, merged recursively.
    scalar        scalar value.
    scalar_list   accepts either a single value or a list (Go's badoption.Listable).

Why this must be generated rather than hand-written: a hand-written table drifts away
from upstream, exactly like configs.py drifted from README.md in this repository.

Why the criterion is "reference namespace" rather than "has a tag": in sing-box 1.14
DNSRuleMatchResponse.Tag makes the elements of dns.rules carry a tag too, but that tag is
the response label of the `respond` action, not a rule identity. dns.rules remains an
ordered collection where the first match wins. Only a tag that something can reference
constitutes an addressing namespace.

Usage:
    sing-box schema > schema/sing-box-<version>.json
    python tools/gen_surface.py schema/sing-box-<version>.json -o schema/surface.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

MAX_DEPTH = 6
MAX_PATHS = 40000

# Collection path -> the reference namespace its tag belongs to.
#
# This table is declarative knowledge about sing-box, not a guess. The generator
# verifies that every namespace really exists in the schema and that every path really
# is a tagged collection, so an upstream rename fails loudly instead of drifting
# silently. Source of truth: the `reference:"..."` struct tags in option/*.go.
TAG_NAMESPACE: dict[str, str] = {
    "outbounds": "outbound",
    "inbounds": "inbound",
    "endpoints": "outbound",  # shares the outbound tag space, see option.checkOutbounds
    "dns.servers": "dns_server",
    "route.rule_set": "rule_set",
    "network_namespaces": "network_namespace",
    "certificate_providers": "certificate_provider",
    "http_clients": "http_client",
}

#: How two classifications of the same path combine. A field declared by several variants
#: of a polymorphic object is only as narrow as the widest of them: if one variant accepts
#: a list, the field accepts a list.
KIND_MERGE: dict[frozenset[str], str] = {
    frozenset({"scalar", "scalar_list"}): "scalar_list",
    frozenset({"scalar", "object"}): "object_or_scalar",
    frozenset({"scalar", "object_or_scalar"}): "object_or_scalar",
    frozenset({"object", "object_or_scalar"}): "object_or_scalar",
}


def merge_kind(path: str, left: str, right: str, conflicts: list[str]) -> str:
    """Combine two slot kinds, recording the pairs that have no common shape."""
    if left == right:
        return left
    merged = KIND_MERGE.get(frozenset({left, right}))
    if merged is None:
        conflicts.append(f"{path}: {left} and {right} have no common shape; kept {left}")
        return left
    return merged


def reference_kinds(schema: dict) -> set[str]:
    """Collect every x-tag-reference value in the whole document."""
    found: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            value = node.get("x-tag-reference")
            if isinstance(value, str) and value:
                found.add(value)
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(schema)
    return found


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def ref_name(node: object) -> str | None:
    ref = node.get("$ref") if isinstance(node, dict) else None
    if isinstance(ref, str):
        return ref.rsplit("/", 1)[-1]
    return None


class SurfaceBuilder:
    def __init__(self, schema: dict) -> None:
        self.schema = schema
        self.defs: dict = schema.get("$defs", {}) or {}
        self.slots: dict[str, dict] = {}
        self.references: dict[str, str] = {}
        self.known_reference_kinds: set[str] = reference_kinds(schema)
        self.tagged_collections: list[str] = []
        self.kind_conflicts: list[str] = []

    def deref(self, node: object) -> dict:
        """Follow a $ref chain (loop-safe)."""
        for _ in range(16):
            if not isinstance(node, dict):
                return {}
            name = ref_name(node)
            if name is None or name not in self.defs:
                return node
            node = self.defs[name]
        return node if isinstance(node, dict) else {}

    def collect_props(self, node: object, stack: tuple[str, ...]) -> dict[str, dict]:
        """Merge the properties of every branch of a polymorphic node.

        A property name may be declared differently by different variants, so the shapes
        are combined rather than overwritten. See `_shapes`.
        """
        node = self.deref(node)
        props: dict[str, dict] = {}
        for branch_key in ("oneOf", "allOf", "anyOf"):
            for branch in node.get(branch_key, []) or []:
                name = ref_name(branch)
                if name is not None:
                    if name in stack:
                        continue
                    self._merge_props(props, self.collect_props(branch, stack + (name,)))
                elif isinstance(branch, dict):
                    self._merge_props(props, self.collect_props(branch, stack))
        own = node.get("properties")
        if isinstance(own, dict):
            self._merge_props(props, own)
        return props

    def _merge_props(self, target: dict[str, dict], incoming: dict[str, dict]) -> None:
        for name, child in incoming.items():
            if name not in target:
                target[name] = child
                continue
            shapes = self._shapes(target[name])
            for shape in self._shapes(child):
                if shape not in shapes:
                    shapes.append(shape)
            target[name] = shapes[0] if len(shapes) == 1 else {"anyOf": shapes}

    def _shapes(self, node: object) -> list[dict]:
        """The alternatives a node accepts, with one level of anyOf flattened.

        A name declared twice in a polymorphic node is not necessarily declared the same
        way: `transport.host` is `string | array` in the http variant and plain `string` in
        httpupgrade. Keeping whichever came last loses the array form, and the surface then
        claims a value sing-box accepts is out of bounds.
        """
        node = self.deref(node)
        if "anyOf" in node and "type" not in node:
            found: list[dict] = []
            for branch in node["anyOf"] or []:
                for shape in self._shapes(branch):
                    if shape not in found:
                        found.append(shape)
            return found
        return [node]

    def array_kind(self, items: object, path: str, stack: tuple[str, ...]) -> str:
        if "tag" not in self.collect_props(items, stack):
            return "seq"
        self.tagged_collections.append(path)
        namespace = TAG_NAMESPACE.get(path)
        if namespace is not None and namespace in self.known_reference_kinds:
            return "map_tag"
        # Tagged but unreferenced: the tag is only a label, order still matters.
        return "seq_tagged"

    def record(
        self,
        path: str,
        kind: str,
        *,
        enum: list | None = None,
        open: bool = False,
    ) -> None:
        existing = self.slots.get(path)
        if existing is None:
            entry: dict = {"kind": kind}
            if enum:
                entry["enum"] = list(enum)
            if open:
                entry["open"] = True
            self.slots[path] = entry
            return

        # A path reached twice was reached through two variants of the same object, so the
        # two value sets are alternatives the field accepts, not competing claims: the union
        # is exactly the accepted set. Keeping only the first is what recorded
        # `route.rule_set{tag}.type` as `["inline", ""]` while the build legitimately writes
        # `remote`, which made the enum unusable for validation.
        existing["kind"] = merge_kind(path, existing["kind"], kind, self.kind_conflicts)
        if enum:
            known = existing.setdefault("enum", [])
            known.extend(value for value in enum if value not in known)
        if open:
            existing["open"] = True

    def walk(self, node: object, path: str, depth: int, stack: tuple[str, ...]) -> None:
        if depth > MAX_DEPTH or len(self.slots) > MAX_PATHS:
            return
        name = ref_name(node)
        if name is not None:
            if name in stack:
                return
            stack = stack + (name,)
        node = self.deref(node)
        if not isinstance(node, dict) or not node:
            return

        # Field that accepts several shapes. The array form is the common Listable case;
        # the object form matters because a contribution may want to write into it, e.g.
        # http_client is either a tag string or inline options with a detour.
        #
        # Every branch is walked, not just the first: a field declared by two variants keeps
        # the properties of both, otherwise the surface would lose half of them.
        if "anyOf" in node and "type" not in node:
            branches = [self.deref(b) for b in (node["anyOf"] or []) if isinstance(b, dict)]

            def shape_of(branch: dict) -> str:
                kind = branch.get("type")
                if isinstance(kind, str):
                    return kind
                return "object" if ("properties" in branch or "oneOf" in branch) else "scalar"

            arrays = [b for b in branches if shape_of(b) == "array"]
            objects = [b for b in branches if shape_of(b) == "object"]
            scalars = [b for b in branches if b not in arrays and b not in objects]
            # The scalar branches are alternatives of one path, so the accepted values are
            # their union - not the first branch's alone, which is how `type` of a
            # rule-set ended up offering `inline` and nothing else.
            enum: list = []
            for branch in scalars:
                for value in self.enum_of(branch):
                    if value not in enum:
                        enum.append(value)
            if arrays:
                # Listable: one element or a list of them. An object alternative is one
                # element of the list, not a different shape of the container, so its
                # properties belong where the element's do.
                self.record(path, "scalar_list", enum=enum)
                for branch in arrays:
                    self.walk(branch.get("items"), path + "[]", depth + 1, stack)
                for branch in objects:
                    self.walk(branch, path + "[]", depth + 1, stack)
                return
            if objects:
                # The branches are alternative shapes of the same path, so they do not
                # consume depth: otherwise a nested Listable one level down would fall off
                # the end of MAX_DEPTH and vanish. Their discriminators are collected by
                # walking each branch, which merges them into `<path>.type`'s enum.
                self.record(path, "object_or_scalar", enum=enum)
                for branch in objects:
                    self.walk(branch, path, depth, stack)
                return
            if scalars:
                self.record(path, "scalar", enum=enum)
                return

        node_type = node.get("type")

        if node_type == "array":
            kind = self.array_kind(node.get("items"), path, stack)
            self.record(path, kind)
            self.walk(
                node.get("items"),
                path + ("{tag}" if kind in ("map_tag", "seq_tagged") else "[]"),
                depth + 1,
                stack,
            )
            return

        if node_type == "object" or "properties" in node or "oneOf" in node:
            # `additionalProperties` holding a schema means the object's keys are data
            # (HTTP header names, SNI values) rather than fields, so they cannot be listed.
            self.record(
                path,
                "object",
                open=node.get("additionalProperties") not in (None, False),
            )
            for prop, child in self.collect_props(node, stack).items():
                child_path = f"{path}.{prop}" if path else prop
                self.record_reference(child_path, child)
                self.walk(child, child_path, depth + 1, stack)
            return

        self.record(path, "scalar", enum=self.enum_of(node) or None)

    def record_reference(self, path: str, node: object) -> None:
        """Mark a tag reference, looking through the shapes a merged node may hold.

        Variants that share a field name may point at different namespaces - `detour` is an
        outbound on most endpoints and an inbound on services - so a disagreement is
        recorded rather than silently resolved.
        """
        for shape in self._shapes(node):
            ref = shape.get("x-tag-reference")
            if not isinstance(ref, str) or not ref:
                continue
            known = self.references.get(path)
            if known is None:
                self.references[path] = ref
            elif known != ref:
                self.kind_conflicts.append(
                    f"{path}: reference {known} and {ref} disagree; kept {known}"
                )
            return

    @staticmethod
    def enum_of(node: object) -> list:
        """The values a scalar accepts, whether they are spelled `enum` or `const`.

        Go's schema generator writes the discriminator of an "only this variant" object as
        `const` rather than a one-element `enum`, so reading only `enum` loses those values:
        a rule-set declared `const: remote` recorded no accepted value at all.
        """
        if not isinstance(node, dict):
            return []
        values = node.get("enum")
        if values:
            return list(values)
        const = node.get("const")
        return [const] if const is not None else []

    def build(self) -> None:
        for prop, child in (self.schema.get("properties") or {}).items():
            self.walk(child, prop, 1, ())
        # References are merged last so the slot kind is already known.
        for path, ref in sorted(self.references.items()):
            if path in self.slots:
                self.slots[path].setdefault("reference", ref)
            else:
                self.slots[path] = {"kind": "scalar", "reference": ref}

    def validate(self) -> tuple[list[str], list[str]]:
        """Check the declarative namespace table against the schema.

        Returns (errors, notes):
          errors — table and schema disagree; upstream drift, fail under --strict
          notes  — tagged but unregistered; classified seq_tagged, which is expected
        """
        errors: list[str] = []
        notes: list[str] = []
        for path, namespace in sorted(TAG_NAMESPACE.items()):
            if namespace not in self.known_reference_kinds:
                errors.append(
                    f"TAG_NAMESPACE[{path!r}] = {namespace!r}, but the schema has no such "
                    f"reference kind"
                )
            if path not in self.slots:
                errors.append(f"TAG_NAMESPACE[{path!r}] points at a path absent from the surface")
            elif self.slots[path]["kind"] not in ("map_tag", "seq_tagged"):
                errors.append(
                    f"TAG_NAMESPACE[{path!r}] is not a tagged collection "
                    f"(got {self.slots[path]['kind']})"
                )
        for path in sorted(self.tagged_collections):
            if path not in TAG_NAMESPACE:
                notes.append(f"{path} — tagged but no reference namespace, classified seq_tagged")
        for conflict in self.kind_conflicts:
            notes.append(f"{conflict} — the surface is lossy here")
        return errors, notes


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Generate the sing-box field surface")
    parser.add_argument("schema", type=Path, help="sing-box schema JSON")
    parser.add_argument("-o", "--output", type=Path, default=None)
    parser.add_argument("--binary-version", default=None, help="recorded in the output")
    parser.add_argument("--strict", action="store_true", help="exit non-zero on errors")
    args = parser.parse_args(argv)

    builder = SurfaceBuilder(load(args.schema))
    builder.build()

    grouped: dict[str, list[str]] = {}
    for path, entry in builder.slots.items():
        grouped.setdefault(entry["kind"], []).append(path)
    for paths in grouped.values():
        paths.sort()

    doc = {
        "source": {
            "schema_file": args.schema.name,
            "binary_version": args.binary_version,
            "top_level": sorted((builder.schema.get("properties") or {}).keys()),
        },
        "counts": {kind: len(paths) for kind, paths in sorted(grouped.items())},
        "tag_namespace": dict(sorted(TAG_NAMESPACE.items())),
        "reference_kinds": sorted(builder.known_reference_kinds),
        "slots": dict(sorted(builder.slots.items())),
    }

    text = json.dumps(doc, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
        print(f"wrote {args.output} ({len(text)} bytes)", file=sys.stderr)

    log = sys.stderr
    print("=== slot counts ===", file=log)
    for kind, paths in sorted(grouped.items()):
        print(f"  {kind:12s} {len(paths):5d}", file=log)
    print("\n=== map_tag (addressed and merged by tag) ===", file=log)
    for path in grouped.get("map_tag", []):
        print(f"  {path:26s} -> {TAG_NAMESPACE.get(path)}", file=log)
    print("\n=== seq_tagged (ordered, tag usable only as an anchor) ===", file=log)
    for path in grouped.get("seq_tagged", []):
        print(f"  {path}", file=log)
    print("\n=== seq (ordered, positioned by anchor) ===", file=log)
    for path in grouped.get("seq", []):
        print(f"  {path}", file=log)
    print("\n=== reference kinds ===", file=log)
    for kind in doc["reference_kinds"]:
        print(f"  {kind}", file=log)

    errors, notes = builder.validate()
    if notes:
        print("\n=== notes ===", file=log)
        for note in notes:
            print(f"  - {note}", file=log)
    if errors:
        print("\n=== errors (namespace table disagrees with the schema) ===", file=log)
        for error in errors:
            print(f"  ! {error}", file=log)
    else:
        print("\nok: the namespace table matches the schema.", file=log)
    if args.strict and errors:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
