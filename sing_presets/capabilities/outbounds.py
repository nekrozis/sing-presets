"""Outbound groups: a manual selector over an auto-tested group.

The node tags themselves are not contributed here. They come from the subscription, which
appends them to the member lists, so this capability declares only the structure and the
default exit. Empty lists are declared on purpose: they say where the subscription is
expected to fill in.
"""

from __future__ import annotations

from typing import Iterable

from ..capability import Capability
from ..facts import Facts
from ..ir import Contribution
from .dns import DIRECT as DNS_DIRECT

DIRECT = "direct"
AUTO = "auto"
PROXY = "proxy"


class OutboundGroups(Capability):
    id = "outbound-groups"
    owns = (
        f"outbounds{{{DIRECT}}}",
        f"outbounds{{{AUTO}}}",
        f"outbounds{{{PROXY}}}",
        "route.final",
    )

    def contribute(self, facts: Facts) -> Iterable[Contribution]:
        yield self.member("outbounds", DIRECT, type="direct", domain_resolver=DNS_DIRECT)

        # Filled by the subscription: every discovered node joins the auto-tested group.
        yield self.member("outbounds", AUTO, type="urltest", outbounds=[])
        yield self.member(
            "outbounds", PROXY, type="selector", outbounds=[AUTO], default=AUTO
        )

        yield self.setting("route.final", PROXY, priority=10)
