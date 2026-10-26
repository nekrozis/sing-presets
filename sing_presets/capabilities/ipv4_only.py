"""The exception for environments without public IPv6.

Dual stack is the default, because it is the common case: `tun-inbound` puts a ULA IPv6
range in the address list and nothing restricts resolution. A machine with no public IPv6
adds this capability, which stops AAAA records from being requested at all.

Keeping it as a capability rather than a conditional inside another one means the normal
path carries no branch for it, and switching it on or off never touches a field that
belongs to something else.
"""

from __future__ import annotations

from typing import Iterable

from ..capability import Capability
from ..facts import Facts
from ..ir import Contribution

STRATEGY = "ipv4_only"


class Ipv4Only(Capability):
    id = "ipv4-only"
    owns = ("dns.strategy",)

    def contribute(self, facts: Facts) -> Iterable[Contribution]:
        yield self.setting("dns.strategy", STRATEGY, priority=20)
