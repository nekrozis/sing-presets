"""The compiler: what it refuses, and what it produces.

Most of these tests are about rejection. A build system that silently emits a broken
configuration is worse than one that fails, because the failure surfaces later, on the
device, as "sing-box will not start".
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sing_presets import capability as cap
from sing_presets import compile as comp
from sing_presets import presets as preset_lib
from sing_presets.surface import Surface

NODES = [
    {"tag": "node-a", "type": "shadowsocks", "server": "198.51.100.1",
     "server_port": 8388, "method": "aes-128-gcm", "password": "x"},
    {"tag": "node-b", "type": "shadowsocks", "server": "198.51.100.2",
     "server_port": 8388, "method": "aes-128-gcm", "password": "x"},
]


@pytest.fixture(scope="module")
def surface() -> Surface:
    return Surface.load()


def write_presets(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "presets.yaml"
    path.write_text(body, encoding="utf-8")
    return path


MINIMAL = """
defaults:
  facts: {device.mtu: 1500}
  capabilities: [logging, tun-inbound, dns-split, outbound-groups, route-baseline]
presets:
  one:
    facts:
      device.tun_address: ["172.18.0.1/30"]
"""


def test_a_minimal_preset_compiles(surface: Surface, tmp_path: Path) -> None:
    document = preset_lib.load(write_presets(tmp_path, MINIMAL))
    build = comp.compile_preset(surface, document.presets["one"], NODES)
    assert build.report.conflicts == []
    assert surface.check_config(build.config) == []
    assert surface.check_references(build.config) == []


def test_the_subscription_capability_is_added_only_when_nodes_exist(
    surface: Surface, tmp_path: Path
) -> None:
    document = preset_lib.load(write_presets(tmp_path, MINIMAL))
    with_nodes = comp.compile_preset(surface, document.presets["one"], NODES)
    assert "subscription-nodes" in with_nodes.capabilities
    assert [item["tag"] for item in with_nodes.config["outbounds"]] == [
        "direct", "auto", "proxy", "node-a", "node-b"
    ]


def test_nodes_join_both_groups(surface: Surface, tmp_path: Path) -> None:
    document = preset_lib.load(write_presets(tmp_path, MINIMAL))
    config = comp.compile_preset(surface, document.presets["one"], NODES).config
    groups = {item["tag"]: item for item in config["outbounds"]}
    assert groups["auto"]["outbounds"] == ["node-a", "node-b"]
    assert groups["proxy"]["outbounds"] == ["auto", "node-a", "node-b"]


def test_duplicate_node_tags_are_rejected(surface: Surface, tmp_path: Path) -> None:
    document = preset_lib.load(write_presets(tmp_path, MINIMAL))
    twice = [NODES[0], dict(NODES[1], tag="node-a")]
    with pytest.raises(comp.CompileError, match="duplicate node tag 'node-a'"):
        comp.compile_preset(surface, document.presets["one"], twice)


def test_an_empty_subscription_is_rejected(surface: Surface, tmp_path: Path) -> None:
    """sing-box refuses an urltest group with no members, so the build must fail first."""
    document = preset_lib.load(write_presets(tmp_path, MINIMAL))
    with pytest.raises(comp.CompileError, match="collections left empty"):
        comp.compile_preset(surface, document.presets["one"], [])


def test_a_dangling_reference_is_rejected(surface: Surface, tmp_path: Path) -> None:
    """A group pointing at a node that is not in the build is a startup failure."""
    body = """
defaults:
  capabilities: [logging, tun-inbound, dns-split, outbound-groups, route-baseline]
presets:
  one:
    facts:
      device.tun_address: ["172.18.0.1/30"]
      device.mtu: 1500
"""
    document = preset_lib.load(write_presets(tmp_path, body))
    build = comp.compile_preset(surface, document.presets["one"], NODES)
    config = build.config
    config["route"]["final"] = "missing-group"
    assert "route.final: 'missing-group' is not defined in outbounds or endpoints" in (
        surface.check_references(config)
    )


def test_every_preset_in_the_repository_builds(surface: Surface) -> None:
    root = Path(__file__).resolve().parent.parent
    document = preset_lib.load(root / "presets.yaml")
    builds = comp.compile_all(surface, document.presets.values(), NODES)
    assert [build.preset for build in builds] == document.names
    for build in builds:
        assert surface.check_config(build.config) == []
        assert surface.check_references(build.config) == []


def test_a_missing_dependency_names_what_to_add(surface: Surface, tmp_path: Path) -> None:
    """Failing on the dependency must explain the preset, not the compiler internals."""
    body = MINIMAL.replace("outbound-groups, ", "")
    document = preset_lib.load(write_presets(tmp_path, body))
    with pytest.raises(comp.CompileError, match="depends on outbound-groups"):
        comp.compile_preset(surface, document.presets["one"], NODES)


def test_compile_all_reports_every_failure(surface: Surface, tmp_path: Path) -> None:
    """Fixing a preset document should not be a one-error-at-a-time exercise."""
    body = """
defaults:
  facts: {device.mtu: 1500}
  capabilities: [logging, tun-inbound]
presets:
  a: {facts: {device.tun_address: ["172.18.0.1/30"]}}
  b: {facts: {device.tun_address: ["172.18.0.2/30"]}}
"""
    document = preset_lib.load(write_presets(tmp_path, body))
    with pytest.raises(comp.CompileError) as caught:
        comp.compile_all(surface, document.presets.values(), NODES)
    message = str(caught.value)
    assert "a:" in message and "b:" in message


def test_a_missing_fact_is_reported_as_a_compile_error(surface: Surface, tmp_path: Path) -> None:
    """A capability raises FactsError, which is not a CompileError and used to escape.

    The user then saw a traceback naming one fact instead of the summary that says which
    preset is broken.
    """
    body = """
defaults:
  capabilities: [logging, tun-inbound]
presets:
  one: {}
"""
    document = preset_lib.load(write_presets(tmp_path, body))
    with pytest.raises(comp.CompileError, match="tun-inbound' needs undeclared facts"):
        comp.compile_preset(surface, document.presets["one"])


def test_compile_all_collects_failures_that_are_not_compile_errors(
    surface: Surface, tmp_path: Path
) -> None:
    """The "report every preset" promise has to hold for missing facts too, not just for
    the errors compile_all already knew about."""
    body = """
defaults:
  capabilities: [logging, tun-inbound]
presets:
  a: {}
  b: {}
"""
    document = preset_lib.load(write_presets(tmp_path, body))
    with pytest.raises(comp.CompileError) as caught:
        comp.compile_all(surface, document.presets.values(), NODES)
    message = str(caught.value)
    assert "a:" in message and "b:" in message


def test_a_value_outside_the_field_enum_is_rejected(surface: Surface, tmp_path: Path) -> None:
    """Spelling a value wrong must fail here rather than on the device.

    `log.level: verbose` is the smallest example; the same check covers outbound types,
    transports and rule actions, none of which the binary can be asked about when it is
    absent or `--no-verify` is in use.
    """
    body = MINIMAL.replace("device.mtu: 1500", "device.mtu: 1500, log.level: verbose")
    document = preset_lib.load(write_presets(tmp_path, body))
    with pytest.raises(comp.CompileError, match="log.level: 'verbose' is not one of"):
        comp.compile_preset(surface, document.presets["one"], NODES)


def test_only_the_collections_sing_box_needs_are_required_to_have_members() -> None:
    """An empty list is usually legal; reporting every one of them is a false-positive trap.

    `route.rule_set: []` is a configuration without rule sets, and `outbounds{auto}` seeds
    its member list empty on purpose so the subscription can fill it.
    """
    assert comp._check_empty_lists({"route": {"rule_set": [], "rules": []}}) == []
    assert comp._check_empty_lists({"outbounds": []}) == ["outbounds"]
    assert comp._check_empty_lists(
        {"outbounds": [{"tag": "auto", "type": "urltest", "outbounds": []}]}
    ) == ["outbounds{auto}.outbounds"]
