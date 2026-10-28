"""Point the transport's host header at a name the preset chooses.

A websocket connection names its destination twice. The TCP connection goes to the address
in the link, and the handshake carries a `Host` header that says which site the request is
for. The server in front decides on the second one: a CDN routes on it, and a host that
serves several names picks its certificate with it. The link that produced the node already
filled it in, from the same field that named the server, so the two agree by default.

This capability replaces the header after the fact. That is the only way to express the
cases where the two must disagree - a handshake through an address the operator has and a
name the operator does not own - because the header is the only field that carries it.

Only transports that hold the host in a header map are touched. `http` and `httpupgrade`
state it in a `host` field of their own, and writing a header there is a field sing-box
rejects, so those nodes are left exactly as the subscription wrote them. A subscription
with no node this applies to fails the build instead of producing a preset that looks like
it does something and does not.

The address is a fact rather than a per-node value, because the disguise is a property of
the deployment - one name for the whole tunnel - while the nodes are whatever the
subscription last served.
"""

from __future__ import annotations

from typing import Any, Iterable

from ..capability import Capability
from ..facts import Facts, FactsError
from ..ir import Contribution

#: Transports that carry the host as a header. Everything else either has no host concept
#: (grpc, quic) or states it in a field of its own (http, httpupgrade).
HEADER_TRANSPORTS = frozenset({"ws"})


def _host_of(value: str) -> str:
    """Validate the fact as something that can be put in a header.

    A header value cannot hold whitespace or a newline, and a slash would turn it into a
    URL. Rejecting those here names the fact; letting them through produces a configuration
    that sing-box accepts and the server rejects, or worse, a second header.
    """
    host = value.strip()
    if not host:
        raise FactsError("transport.host is empty")
    if any(char.isspace() for char in host) or "/" in host:
        raise FactsError(f"transport.host {value!r} is not a host name")
    return host


class TransportHost(Capability):
    id = "transport-host"
    requires = ("transport.host", "subscription.nodes")
    depends_on = ("subscription-nodes",)

    def contribute(self, facts: Facts) -> Iterable[Contribution]:
        host = _host_of(facts.get_str("transport.host"))
        nodes: list[dict[str, Any]] = list(facts.require("subscription.nodes"))
        applied = 0
        for node in nodes:
            transport = node.get("transport")
            if not isinstance(transport, dict) or transport.get("type") not in HEADER_TRANSPORTS:
                continue
            tag = node.get("tag")
            if not isinstance(tag, str) or not tag:
                raise FactsError(
                    "a subscription node has no tag, so its transport host cannot be addressed"
                )
            applied += 1
            yield self.setting(
                f"outbounds{{{tag}}}.transport.headers.Host", host, priority=10, override=True
            )
        if not applied:
            kinds = sorted(
                {
                    str(node.get("transport", {}).get("type", "none"))
                    for node in nodes
                    if isinstance(node.get("transport"), dict)
                }
            )
            raise FactsError(
                "transport.host is set and the preset includes transport-host, but no node "
                f"carries its host in a header (transports present: {', '.join(kinds) or 'none'})"
            )
