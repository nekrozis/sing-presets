"""The exception for environments without public IPv6.

Dual stack is the default, because it is the common case: `tun-inbound` puts a ULA IPv6
range in the address list and nothing restricts resolution. A machine with no public IPv6
adds this capability.

The exception is stated as a DNS answer. An AAAA query for a name that will be dialled from
here comes back as an empty NOERROR, which is indistinguishable from a name that has no
IPv6 address, so the client is told there is none rather than being handed one it cannot
reach. A resolution strategy would only narrow the lookups sing-box performs on the
client's behalf: an application that resolves on its own, or that keeps a literal from an
earlier answer, never meets it - and the address it holds is the one that cannot be dialled.

Which queries are covered follows from where the answer comes from, not from where the
traffic ends up. A resolver that answers from this machine hands back addresses this
machine has to dial itself, and on a network without public IPv6 none of them work; a
resolver reached through the tunnel hands back addresses the far side dials, so its IPv6
answers are still good. Every rule that picks a resolver of the first kind therefore gets
the empty answer in front of it, under the same condition that rule uses:

  * `clash_mode: direct` - every name, because nothing is tunnelled in that mode;
  * the domestic rule set - domestic names, which resolve locally in every mode.

The `clash_mode: global` rule is deliberately left alone: it resolves through the tunnel,
so IPv6 works there and there is nothing to withhold.

Both guards sit in one band ahead of the direct-resolver rules rather than between them.
That is all the order they need - a query they match would otherwise be answered by one of
those rules, and first match wins - and it leaves those rules next to each other, where
they fold into one rule instead of being split by a guard.

Only names need it. The private and BitTorrent rules match an address or a protocol, which
no answer can change, and the domestic address rule already matches addresses.

The rule set belongs to `china-split` and the mode rule to `dns-split`, so switching this
on without them would reference a tag nobody defines or guard a rule nobody wrote.
`depends_on` says that in one place, and the build checks it before it gets that far.
"""

from __future__ import annotations

from typing import Iterable

from ..capability import Capability
from ..facts import Facts
from ..ir import Contribution, Position
from .dns import MODE_DIRECT
from .ordering import DnsRank
from .routing import CN_DOMAIN_RULE_SET

#: An answer that says "this name has no IPv6 address" without consulting anything.
EMPTY_AAAA = {"action": "predefined", "rcode": "NOERROR", "query_type": "AAAA"}


class Ipv4Only(Capability):
    id = "ipv4-only"
    depends_on = ("china-split", "dns-split")

    def contribute(self, facts: Facts) -> Iterable[Contribution]:
        yield self.entry(
            "dns.rules",
            {**EMPTY_AAAA, "clash_mode": MODE_DIRECT},
            Position.at(DnsRank.NO_AAAA),
        )
        yield self.entry(
            "dns.rules",
            {**EMPTY_AAAA, "rule_set": [CN_DOMAIN_RULE_SET]},
            Position.at(DnsRank.NO_AAAA),
        )
