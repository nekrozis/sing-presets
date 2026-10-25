"""Integration test: a compiled configuration must be accepted by the real sing-box.

The field surface guarantees that every path exists; only the binary can tell us whether
the values make sense together. This test closes that loop, so the merge algebra is
validated against the same tool that will run the output in CI.

Set SING_BOX to the binary, or make sure `sing-box` is on PATH. The test is skipped when
no binary is available, so the unit suite still runs on a bare machine.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from sing_presets import capability as cap
from sing_presets.facts import Facts
from sing_presets.ir import Anchor, Builder, Entry, Position, Setting, compile_config
from sing_presets.surface import Surface

CANDIDATES = (
    os.environ.get("SING_BOX"),
    shutil.which("sing-box"),
    r"C:\Users\Lyra\scoop\shims\sing-box.exe",
)


def find_sing_box() -> str | None:
    for candidate in CANDIDATES:
        if candidate and Path(candidate).exists():
            return candidate
    return None


SING_BOX = find_sing_box()
requires_sing_box = pytest.mark.skipif(SING_BOX is None, reason="sing-box binary not available")


def sing_box_command(*args: str) -> list[str]:
    """Build a command line, failing loudly if the binary is missing."""
    if SING_BOX is None:
        raise RuntimeError("sing-box binary not available")
    return [SING_BOX, *args]


class TunInbound(cap.Capability):
    id = "it-tun"
    requires = ("device.tun_address", "device.mtu")
    owns = ("inbounds{tun-in}",)

    def contribute(self, facts: Facts):
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


class DnsSplit(cap.Capability):
    id = "it-dns"
    requires = ("network.has_public_ipv6",)

    def contribute(self, facts: Facts):
        yield self.member("dns.servers", "dns-local", type="tcp", server="180.184.1.1")
        yield self.member(
            "dns.servers", "dns-direct", type="tls", server="dot.pub",
            domain_resolver="dns-local",
        )
        yield self.member(
            "dns.servers", "dns-remote", type="tls", server="dns11.quad9.net",
            domain_resolver="dns-direct", detour="proxy",
        )
        yield Setting("dns.final", "dns-remote", priority=10, owner="")
        strategy = "prefer_ipv6" if facts.require_bool("network.has_public_ipv6") else "ipv4_only"
        yield self.setting("dns.strategy", strategy, priority=20)
        yield self.anchor("dns.rules", "ads", 100)
        yield self.entry(
            "dns.rules", {"action": "reject", "rule_set": ["geosite-category-ads-all"]},
            Position.at(100),
        )
        yield self.entry(
            "dns.rules", {"server": "dns-direct", "rule_set": ["geosite-cn"]},
            Position.after("ads"),
        )


class RouteRules(cap.Capability):
    id = "it-route"
    owns = ("route.rule_set{geosite-cn}", "route.rule_set{geosite-category-ads-all}")

    def contribute(self, facts: Facts):
        for tag in ("geosite-cn", "geosite-category-ads-all"):
            yield self.member(
                "route.rule_set",
                tag,
                type="remote",
                format="binary",
                url=f"https://example.invalid/{tag}.srs",
                http_client={"detour": "direct"},
            )
        yield self.entry("route.rules", {"action": "sniff"}, Position.first())
        yield self.entry(
            "route.rules", {"action": "hijack-dns", "protocol": "dns"}, Position.at(10)
        )
        yield self.entry(
            "route.rules", {"outbound": "direct", "ip_is_private": True}, Position.at(20)
        )
        yield self.entry(
            "route.rules",
            {"action": "reject", "rule_set": ["geosite-category-ads-all"]},
            Position.at(30),
        )
        yield self.entry(
            "route.rules", {"outbound": "direct", "rule_set": ["geosite-cn"]}, Position.at(40)
        )
        yield self.setting("route.final", "proxy", priority=10)
        yield self.setting("route.auto_detect_interface", True, priority=10)
        yield self.setting("route.default_domain_resolver", "dns-direct", priority=10)


class ProxyGroup(cap.Capability):
    id = "it-proxy"
    owns = ("outbounds{proxy}", "outbounds{auto}", "outbounds{direct}")

    def contribute(self, facts: Facts):
        yield self.member("outbounds", "direct", type="direct", domain_resolver="dns-direct")
        yield self.member("outbounds", "auto", type="urltest", outbounds=[])
        yield self.member(
            "outbounds", "proxy", type="selector", outbounds=["auto"], default="auto"
        )


class Nodes(cap.Capability):
    """Stands in for the subscription pipeline that injects discovered nodes.

    It extends members owned by `it-proxy`, so it declares the dependency instead of
    relying on it implicitly.
    """

    id = "it-nodes"
    depends_on = ("it-proxy",)

    def contribute(self, facts: Facts):
        for tag, host in (("node-jp", "198.51.100.1"), ("node-sg", "203.0.113.1")):
            yield self.member(
                "outbounds", tag, type="shadowsocks", server=host, server_port=8388,
                method="aes-128-gcm", password="secret",
            )
        for tag in ("node-jp", "node-sg"):
            yield self.entry("outbounds{auto}.outbounds", tag)
            yield self.entry("outbounds{proxy}.outbounds", tag, Position.at(50))


def compile_for(has_public_ipv6: bool):
    surface = Surface.load()
    capabilities = cap.build_registry(["it-tun", "it-dns", "it-route", "it-proxy", "it-nodes"])
    facts = Facts.of(
        **{
            "device.tun_address": ["172.18.0.1/30"],
            "device.mtu": 9000,
            "network.has_public_ipv6": has_public_ipv6,
        }
    )
    contributions = [item for capability in capabilities for item in capability.contributions(facts)]
    tree, report = compile_config(surface, contributions)
    return surface, tree, report, contributions


@pytest.mark.parametrize("has_public_ipv6", [True, False])
@requires_sing_box
def test_compiled_config_is_accepted_by_sing_box(tmp_path: Path, has_public_ipv6: bool) -> None:
    surface, tree, report, _ = compile_for(has_public_ipv6)
    assert report.conflicts == []
    assert surface.check_config(tree) == []

    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(tree, indent=2), encoding="utf-8")
    result = subprocess.run(
        sing_box_command("check", "-c", str(config_file)),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, f"sing-box check failed:\n{result.stdout}\n{result.stderr}"


@requires_sing_box
def test_the_binary_and_the_surface_agree_on_the_version(tmp_path: Path) -> None:
    surface = Surface.load()
    result = subprocess.run(
        sing_box_command("version"), capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0
    assert f"version {surface.binary_version}" in result.stdout, (
        f"surface was generated for {surface.binary_version}, but the binary reports "
        f"{result.stdout.splitlines()[0]!r}"
    )


def test_facts_change_the_output_only_where_intended() -> None:
    """The whole point: one fact flips the v6 strategy and nothing else."""
    _, with_v6, _, _ = compile_for(True)
    _, without_v6, _, _ = compile_for(False)
    assert with_v6["dns"]["strategy"] == "prefer_ipv6"
    assert without_v6["dns"]["strategy"] == "ipv4_only"
    with_v6["dns"].pop("strategy")
    without_v6["dns"].pop("strategy")
    assert with_v6 == without_v6


def test_switch_a_capability_off_and_nothing_else_changes() -> None:
    surface = Surface.load()
    facts = Facts.of(
        **{
            "device.tun_address": ["172.18.0.1/30"],
            "device.mtu": 9000,
            "network.has_public_ipv6": True,
        }
    )
    ids = ["it-tun", "it-dns", "it-route", "it-proxy", "it-nodes"]
    capabilities = cap.build_registry(ids)
    contributions = [
        item for capability in capabilities for item in capability.contributions(facts)
    ]
    dependencies = cap.dependency_map(capabilities)

    # Criterion 3: nobody writes into an address owned by someone else, and no address is
    # claimed twice. The node injector is allowed in because it declares the dependency.
    assert cap.check_ownership(capabilities) == []
    assert cap.check_trespass(contributions, dependencies) == []

    # Criterion 2: each capability can be switched off without disturbing the others.
    assert Builder(surface).verify_isolation(contributions, dependencies) == []

    full = compile_config(surface, contributions)[0]
    without_dns = compile_config(
        surface, [item for item in contributions if item.owner != "it-dns"]
    )[0]
    assert "dns" not in without_dns
    del full["dns"]
    assert full == without_dns
