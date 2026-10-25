"""The local control panel and the on-disk cache.

Both are opt-in: the previous setup always emitted a second configuration file that added
the control panel, which meant keeping two outputs in step. Here it is a capability that
a preset either lists or does not.
"""

from __future__ import annotations

from typing import Iterable

from ..capability import Capability
from ..facts import Facts
from ..ir import Contribution

CONTROLLER_PORT = 9090
UI_NAME = "dashboard"
UI_DOWNLOAD_URL = (
    "https://github.com/MetaCubeX/metacubexd/archive/refs/heads/gh-pages.zip"
)

LOOPBACK = "127.0.0.1"
ANY_ADDRESS = "0.0.0.0"


class ClashApi(Capability):
    id = "clash-api"
    owns = ("experimental.clash_api",)

    def contribute(self, facts: Facts) -> Iterable[Contribution]:
        # Exposing the panel to the local network is a deliberate choice, so it comes
        # from a fact rather than from the capability guessing.
        allow_lan = bool(facts.get("network.allow_lan", False))
        address = ANY_ADDRESS if allow_lan else LOOPBACK

        yield self.setting(
            "experimental.clash_api.external_controller",
            f"{address}:{CONTROLLER_PORT}",
            priority=10,
        )
        yield self.setting(
            "experimental.clash_api.external_ui", UI_NAME, priority=10
        )
        yield self.setting(
            "experimental.clash_api.external_ui_download_url", UI_DOWNLOAD_URL, priority=10
        )
        yield self.setting(
            "experimental.clash_api.secret", facts.get("api.secret", ""), priority=10
        )
        yield self.setting(
            "experimental.clash_api.access_control_allow_private_network",
            allow_lan,
            priority=10,
        )


class CacheFile(Capability):
    id = "cache-file"
    owns = ("experimental.cache_file.enabled", "experimental.cache_file.store_dns")

    def contribute(self, facts: Facts) -> Iterable[Contribution]:
        yield self.setting("experimental.cache_file.enabled", True, priority=10)
        yield self.setting("experimental.cache_file.store_dns", True, priority=10)
