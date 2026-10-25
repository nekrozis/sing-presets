"""Logging settings."""

from __future__ import annotations

from typing import Iterable

from ..facts import Facts
from ..ir import Contribution
from ..capability import Capability

DEFAULT_LEVEL = "info"


class Logging(Capability):
    id = "logging"
    owns = ("log.level",)

    def contribute(self, facts: Facts) -> Iterable[Contribution]:
        yield self.setting("log.level", facts.get("log.level", DEFAULT_LEVEL), priority=10)
