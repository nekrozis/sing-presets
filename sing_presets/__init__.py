"""sing-presets: generate a set of sing-box configurations from a set of preset snapshots.

The design in one line: a preset is a combination of capabilities; a capability only
declares what it produces, and the merge semantics are enforced centrally by the IR
according to the slot kind of each field-surface path.
"""

__all__ = ["capability", "facts", "ir", "surface"]
