"""Routing: the baseline rules, the China split, and ad blocking.

`china-split` and `block-ads` are separate capabilities on purpose. Keeping domestic
traffic direct and dropping ad domains are two different decisions, so a preset can hold
one without the other, and each owns the rule sets it declares.
"""

from __future__ import annotations

from typing import Iterable

from ..capability import Capability
from ..facts import Facts
from ..ir import Contribution, Position
from .dns import DIRECT as DNS_DIRECT
from .ordering import DnsRank, RouteRank
from .outbounds import DIRECT as OUTBOUND_DIRECT, PROXY as OUTBOUND_PROXY

GEOSITE_UPSTREAM = "https://cdn.jsdelivr.net/gh/SagerNet/sing-geosite@refs/heads/rule-set"
GEOIP_UPSTREAM = "https://cdn.jsdelivr.net/gh/SagerNet/sing-geoip@refs/heads/rule-set"

ADS_RULE_SET = "geosite-category-ads-all"
CN_RULE_SETS = ("geosite-cn", "geoip-cn")


def remote_rule_set(tag: str, detour: str = OUTBOUND_DIRECT) -> dict:
    """Build a remote rule-set entry, deriving the upstream from the tag prefix.

    The prefix decides which repository serves the compiled rule set, so a tag with an
    unknown prefix is a mistake rather than something to guess at.
    """
    prefix = tag.split("-", 1)[0]
    if prefix == "geosite":
        upstream = GEOSITE_UPSTREAM
    elif prefix == "geoip":
        upstream = GEOIP_UPSTREAM
    else:
        raise ValueError(f"rule set tag must start with geosite or geoip, got: {tag!r}")
    return {
        "type": "remote",
        "format": "binary",
        "url": f"{upstream}/{tag}.srs",
        "http_client": {"detour": detour},
    }


class RouteBaseline(Capability):
    """The rules that have to come before any split, plus the route-level defaults."""

    id = "route-baseline"
    owns = (
        "route.auto_detect_interface",
        "route.default_domain_resolver",
    )

    def contribute(self, facts: Facts) -> Iterable[Contribution]:
        yield self.entry(
            "route.rules", {"action": "sniff"}, Position.at(RouteRank.SNIFF)
        )
        yield self.entry(
            "route.rules",
            {"action": "hijack-dns", "protocol": "dns"},
            Position.at(RouteRank.HIJACK_DNS),
        )
        # Private destinations never leave the machine, so they are settled first.
        yield self.entry(
            "route.rules",
            {"outbound": OUTBOUND_DIRECT, "ip_is_private": True},
            Position.at(RouteRank.PRIVATE_DIRECT),
        )
        # BitTorrent does not belong in a tunnel, and this is cheaper than rejecting it
        # after the fact.
        yield self.entry(
            "route.rules",
            {"outbound": OUTBOUND_DIRECT, "protocol": "bittorrent"},
            Position.at(RouteRank.BITTORRENT_DIRECT),
        )
        yield self.setting("route.auto_detect_interface", True, priority=10)
        yield self.setting("route.default_domain_resolver", DNS_DIRECT, priority=10)


class ChinaSplit(Capability):
    """Domestic names and addresses go direct, in both routing and resolution."""

    id = "china-split"
    owns = tuple(f"route.rule_set{{{tag}}}" for tag in CN_RULE_SETS)
    #: `direct` comes from outbound-groups, and the domestic-names rule names the direct
    #: resolver from dns-split. Both are tags, so dropping either leaves a rule pointing at
    #: something that is not there.
    depends_on = ("dns-split", "outbound-groups")

    def contribute(self, facts: Facts) -> Iterable[Contribution]:
        for tag in CN_RULE_SETS:
            yield self.member("route.rule_set", tag, **remote_rule_set(tag))

        yield self.entry(
            "route.rules",
            {"outbound": OUTBOUND_DIRECT, "rule_set": ["geosite-cn"]},
            Position.at(RouteRank.CN_DIRECT),
        )
        yield self.entry(
            "route.rules",
            {"outbound": OUTBOUND_DIRECT, "rule_set": ["geoip-cn"]},
            Position.at(RouteRank.CN_IP_DIRECT),
        )
        # Domestic names are resolved by the direct resolver even when the routing mode
        # sends everything else through the tunnel.
        yield self.entry(
            "dns.rules",
            {"server": DNS_DIRECT, "rule_set": ["geosite-cn"]},
            Position.at(DnsRank.CN_DIRECT),
        )


class BlockAds(Capability):
    """Drop ad domains before they can be routed, and refuse to resolve them."""

    id = "block-ads"
    owns = (f"route.rule_set{{{ADS_RULE_SET}}}",)

    def contribute(self, facts: Facts) -> Iterable[Contribution]:
        yield self.member("route.rule_set", ADS_RULE_SET, **remote_rule_set(ADS_RULE_SET))

        yield self.entry(
            "route.rules",
            {"action": "reject", "rule_set": [ADS_RULE_SET]},
            Position.at(RouteRank.ADS_REJECT),
        )
        yield self.entry(
            "dns.rules",
            {"action": "reject", "rule_set": [ADS_RULE_SET]},
            Position.at(DnsRank.ADS_REJECT),
        )


__all__ = [
    "ADS_RULE_SET",
    "BlockAds",
    "ChinaSplit",
    "CN_RULE_SETS",
    "OUTBOUND_PROXY",
    "RouteBaseline",
    "remote_rule_set",
]
