"""Split DNS: a direct resolver for domestic names, a remote resolver for everything else.

Resolvers are policy, not environment, so they are constants here rather than facts. The
two `clash_mode` rules make the resolvers follow the routing mode, which is what the
previous template did.
"""

from __future__ import annotations

from typing import Iterable

from ..capability import Capability
from ..facts import Facts
from ..ir import Contribution, Position
from .ordering import DnsRank

LOCAL = "dns-local"
DIRECT = "dns-direct"
REMOTE = "dns-remote"

#: Plain address, so it needs no resolver of its own and bootstraps the others.
LOCAL_SERVER = "180.184.1.1"
DIRECT_SERVER = "dot.pub"
REMOTE_SERVER = "dns11.quad9.net"


class DnsSplit(Capability):
    id = "dns-split"
    #: The remote resolver detours through the selector that `outbound-groups` defines.
    #: Declared rather than left to the dangling-reference check, which would report a tag
    #: that "is not defined in outbounds" instead of naming the missing capability.
    depends_on = ("outbound-groups",)
    owns = (
        f"dns.servers{{{LOCAL}}}",
        f"dns.servers{{{DIRECT}}}",
        f"dns.servers{{{REMOTE}}}",
    )

    def contribute(self, facts: Facts) -> Iterable[Contribution]:
        yield self.member("dns.servers", LOCAL, type="tcp", server=LOCAL_SERVER)
        yield self.member(
            "dns.servers", DIRECT, type="tls", server=DIRECT_SERVER, domain_resolver=LOCAL
        )
        yield self.member(
            "dns.servers",
            REMOTE,
            type="tls",
            server=REMOTE_SERVER,
            domain_resolver=DIRECT,
            detour="proxy",
        )
        yield self.setting("dns.final", REMOTE, priority=10)

        yield self.entry(
            "dns.rules",
            {"server": REMOTE, "clash_mode": "global"},
            Position.at(DnsRank.CLASH_GLOBAL),
        )
        yield self.entry(
            "dns.rules",
            {"server": DIRECT, "clash_mode": "direct"},
            Position.at(DnsRank.CLASH_DIRECT),
        )
