"""The TUN inbound, which is where device-specific values live.

Dual stack is the default: the address list carries the IPv4 range and a ULA IPv6 range,
which is what the previous single-template setup did. Environments without public IPv6
are the exception and get the `ipv4-only` capability added by the preset, rather than
this capability carrying a conditional for them.
"""

from __future__ import annotations

from typing import Iterable

from ..capability import Capability
from ..facts import Facts
from ..ir import Contribution


class TunInbound(Capability):
    id = "tun-inbound"
    requires = ("device.tun_address", "device.mtu")
    owns = ("inbounds{tun-in}",)

    def contribute(self, facts: Facts) -> Iterable[Contribution]:
        yield self.member(
            "inbounds",
            "tun-in",
            type="tun",
            address=list(facts.require("device.tun_address")),
            mtu=facts.require("device.mtu"),
            auto_route=True,
            strict_route=True,
            stack="gvisor",
        )
