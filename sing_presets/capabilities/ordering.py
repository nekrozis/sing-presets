"""Positions inside the shared ordered lists.

`route.rules` and `dns.rules` are single ordered lists, and sing-box applies the first
rule that matches, so order is semantic. Every capability writes into the same list, so
the ranks have to live in one visible place: a magic number repeated across six modules
is exactly the kind of coupling that drifts without anyone noticing.

When a capability is added, pick a rank here rather than inventing one locally. Leave
gaps, so a later rule can be slotted in without renumbering.
"""

from __future__ import annotations


class RouteRank:
    """Ranks for `route.rules`, low first."""

    SNIFF = 0
    HIJACK_DNS = 10
    PRIVATE_DIRECT = 20
    IPV4_ONLY_REJECT = 30
    ADS_REJECT = 100
    CLASH_GLOBAL = 200
    CLASH_DIRECT = 210
    CN_DIRECT = 300
    CN_IP_DIRECT = 310
    BITTORRENT_DIRECT = 900


class DnsRank:
    """Ranks for `dns.rules`, low first."""

    ADS_REJECT = 100
    CLASH_GLOBAL = 200
    CLASH_DIRECT = 210
    CN_DIRECT = 300


__all__ = ["DnsRank", "RouteRank"]
