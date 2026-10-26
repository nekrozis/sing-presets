"""Facts: the observed or declared properties of an environment.

A capability never hard-codes an environment. It reads facts, which are data, so the same
capability works on every device. This is what removes the orthogonal duplication: one
fact that drives three fields is written once, inside the capability, instead of once per
combination of output file.

Fact keys are dotted paths, e.g. `device.kind`, `network.has_public_ipv6`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping


class FactsError(Exception):
    """A capability asked for a fact that was not declared for this preset."""


@dataclass(frozen=True)
class Facts:
    values: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def of(cls, **kwargs: Any) -> "Facts":
        return cls(values=dict(kwargs))

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)

    def require(self, key: str) -> Any:
        if key not in self.values:
            raise FactsError(f"missing fact: {key}")
        return self.values[key]

    def get_bool(self, key: str, default: bool = False) -> bool:
        """Read a boolean, refusing anything that is merely truthy.

        `bool("false")` is True, so a quoted value - which YAML, a template, or an
        environment variable can produce - would silently turn a loopback-bound control
        panel into one reachable from the network, and write a string where sing-box
        expects a bool. Requiring the type is the only way this fails loudly.
        """
        value = self.values.get(key, default)
        if not isinstance(value, bool):
            raise FactsError(
                f"fact {key} should be a bool, got {type(value).__name__}: {value!r}"
            )
        return value

    def get_str(self, key: str, default: str = "") -> str:
        """Read a string, refusing a number or a bool.

        A port or a level written without quotes parses as a number, and passing it on
        produces a configuration that looks right and is rejected on the device.
        """
        value = self.values.get(key, default)
        if not isinstance(value, str):
            raise FactsError(
                f"fact {key} should be a string, got {type(value).__name__}: {value!r}"
            )
        return value

    def with_overrides(self, overrides: Mapping[str, Any]) -> "Facts":
        merged = dict(self.values)
        merged.update(overrides)
        return Facts(values=merged)

    def check_supported(self, keys: Iterable[str]) -> list[str]:
        """Report fact keys a capability wants but the preset never declared."""
        return sorted(key for key in keys if key not in self.values)
