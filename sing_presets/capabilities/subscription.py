"""The nodes discovered in a subscription.

Nodes are the fast-changing part: a subscription changes daily while the routing policy
changes rarely. They are therefore data rather than code, and this capability is the only
place that knows how they enter a configuration.

sing-box has no node provider mechanism (unlike Clash's `proxy-providers`), so the nodes
must be inline. That is why the pipeline has to regenerate on a schedule rather than
pointing the client at a URL.

It extends the member lists of the groups owned by `outbound-groups`, which is a real
dependency and is declared as one.
"""

from __future__ import annotations

from typing import Any, Iterable

from ..capability import Capability
from ..facts import Facts
from ..ir import Contribution
from .outbounds import AUTO, PROXY


class SubscriptionNodes(Capability):
    id = "subscription-nodes"
    requires = ("subscription.nodes",)
    depends_on = ("outbound-groups",)

    def contribute(self, facts: Facts) -> Iterable[Contribution]:
        nodes: list[dict[str, Any]] = list(facts.require("subscription.nodes"))
        for node in nodes:
            tag = node.get("tag")
            if not tag:
                raise ValueError(f"subscription node without a tag: {node!r}")
            body = {key: value for key, value in node.items() if key != "tag"}
            yield self.member("outbounds", tag, body)
        for node in nodes:
            yield self.entry(f"outbounds{{{AUTO}}}.outbounds", node["tag"])
            # Manual selection lists the individual nodes after the auto group, so
            # picking one by hand does not mean leaving the tested set.
            yield self.entry(f"outbounds{{{PROXY}}}.outbounds", node["tag"])
