"""The capability library: one intent per capability, grouped by area.

A capability reads facts and yields contributions. It never assembles JSON and never
knows which preset uses it. Two rules keep the library orthogonal:

- a capability owns the members it creates, and does not write into another's
  (declare `depends_on` when extending one on purpose)
- ordering inside the shared `route.rules` and `dns.rules` lists comes from
  `ordering.py`, so the sequence is visible in one place instead of being scattered
  as magic numbers
"""

from .dns import DnsSplit
from .ipv4_only import Ipv4Only
from .local_api import CacheFile, ClashApi
from .log import Logging
from .outbounds import OutboundGroups
from .routing import BlockAds, ChinaSplit, RouteBaseline
from .tun import TunInbound

__all__ = [
    "BlockAds",
    "CacheFile",
    "ChinaSplit",
    "ClashApi",
    "DnsSplit",
    "Ipv4Only",
    "Logging",
    "OutboundGroups",
    "RouteBaseline",
    "TunInbound",
]
