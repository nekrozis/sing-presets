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

    def require_bool(self, key: str) -> bool:
        value = self.require(key)
        if not isinstance(value, bool):
            raise FactsError(f"fact {key} should be a bool, got {type(value).__name__}")
        return value

    def require_str(self, key: str) -> str:
        value = self.require(key)
        if not isinstance(value, str):
            raise FactsError(f"fact {key} should be a string, got {type(value).__name__}")
        return value

    def with_overrides(self, overrides: Mapping[str, Any]) -> "Facts":
        merged = dict(self.values)
        merged.update(overrides)
        return Facts(values=merged)

    def check_supported(self, keys: Iterable[str], preset: str = "") -> list[str]:
        """Report fact keys a capability wants but the preset never declared."""
        return sorted(key for key in keys if key not in self.values)
