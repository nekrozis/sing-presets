"""The surface generator: the classification rules that are easy to get wrong.

These are the cases that produced a wrong surface in practice. A field declared by several
variants of the same object is the awkward one: each variant may give it a different shape,
and keeping whichever variant happened to be read last both narrows the field (it then
rejects values sing-box accepts) and hides the properties the other variants contribute.

The schemas below are synthetic on purpose. What is being tested is the rule, not the shape
of sing-box's own schema, so a sing-box upgrade cannot quietly turn these tests into no-ops.
"""

from __future__ import annotations

import gen_surface

from sing_presets.surface import Surface

#: Two variants of one object. `host` is a list or a single value in the first and a plain
#: string in the second; `extra` exists only in the second.
POLYMORPHIC = {
    "$defs": {
        "Box": {
            "oneOf": [
                {
                    "type": "object",
                    "properties": {
                        "type": {"const": "first"},
                        "host": {
                            "anyOf": [
                                {"type": "string"},
                                {"type": "array", "items": {"type": "string"}},
                            ]
                        },
                    },
                },
                {
                    "type": "object",
                    "properties": {
                        "type": {"const": "second"},
                        "host": {"type": "string"},
                        "extra": {"type": "string"},
                        "client": {"$ref": "#/$defs/Client"},
                    },
                },
            ]
        },
        "Client": {"type": "object", "properties": {"detour": {"type": "string"}}},
    },
    "type": "object",
    "properties": {"boxes": {"type": "array", "items": {"$ref": "#/$defs/Box"}}},
}


def build(schema: dict) -> dict:
    builder = gen_surface.SurfaceBuilder(schema)
    builder.build()
    return builder.slots


def test_a_field_declared_with_two_shapes_is_as_wide_as_the_widest() -> None:
    """The http transport accepts a list of hosts; httpupgrade accepts one. The field
    accepts both, so recording only `scalar` would reject valid input."""
    slots = build(POLYMORPHIC)
    assert slots["boxes[].host"]["kind"] == "scalar_list"
    assert slots["boxes[].host[]"]["kind"] == "scalar"


def test_properties_of_every_variant_are_kept() -> None:
    """`extra` exists only in the second variant; dropping it hides a real field."""
    slots = build(POLYMORPHIC)
    assert "boxes[].extra" in slots
    assert "boxes[].client.detour" in slots


def test_the_shipped_surface_lets_a_transport_declare_several_hosts() -> None:
    """Regression guard on the artefact itself, since that is what the build reads."""
    assert Surface.load().kind_of("outbounds{tag}.transport.host") == "scalar_list"
