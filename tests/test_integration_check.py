"""Integration test: a compiled preset must be accepted by the real sing-box.

The field surface guarantees that every path exists; only the binary can tell us whether
the values make sense together. This closes that loop, so the merge algebra is validated
against the same tool that will run the output in CI.

Set SING_BOX to the binary, or make sure `sing-box` is on PATH. The test is skipped when
no binary is available, so the unit suite still runs on a bare machine.
"""

from __future__ import annotations

import base64
import json
import subprocess
from pathlib import Path

import pytest

from sing_presets import compile as comp
from sing_presets import nodes as node_lib
from sing_presets import presets as preset_lib
from sing_presets.cli import find_sing_box
from sing_presets.surface import Surface

SING_BOX = find_sing_box()
requires_sing_box = pytest.mark.skipif(SING_BOX is None, reason="sing-box binary not available")

REPO_ROOT = Path(__file__).resolve().parent.parent
PRESET_FILE = REPO_ROOT / "presets.yaml"

NODES = [
    {
        "tag": "jp-tokyo",
        "type": "shadowsocks",
        "server": "198.51.100.10",
        "server_port": 8388,
        "method": "aes-128-gcm",
        "password": "example",
    },
    {
        "tag": "sg-singapore",
        "type": "shadowsocks",
        "server": "203.0.113.20",
        "server_port": 8388,
        "method": "aes-128-gcm",
        "password": "example",
    },
]


def sing_box_command(*args: str) -> list[str]:
    """Build a command line, failing loudly if the binary is missing."""
    if SING_BOX is None:
        raise RuntimeError("sing-box binary not available")
    return [SING_BOX, *args]


def all_builds() -> list[comp.Build]:
    surface = Surface.load()
    document = preset_lib.load(PRESET_FILE)
    return comp.compile_all(surface, document.presets.values(), NODES)


@pytest.mark.parametrize("name", ["desktop", "desktop-no-v6", "router"])
@requires_sing_box
def test_shipped_presets_are_accepted_by_sing_box(tmp_path: Path, name: str) -> None:
    build = next(item for item in all_builds() if item.preset == name)
    target = tmp_path / f"{name}.json"
    target.write_text(json.dumps(build.config, indent=2), encoding="utf-8")
    result = subprocess.run(
        sing_box_command("check", "-c", str(target)),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, f"sing-box check failed:\n{result.stdout}\n{result.stderr}"


@requires_sing_box
def test_the_binary_and_the_surface_agree_on_the_version() -> None:
    surface = Surface.load()
    result = subprocess.run(
        sing_box_command("version"), capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0
    assert f"version {surface.binary_version}" in result.stdout, (
        f"surface was generated for {surface.binary_version}, but the binary reports "
        f"{result.stdout.splitlines()[0]!r}"
    )


def test_the_v6_exception_changes_exactly_one_field() -> None:
    """The whole point of the design: one fact, one difference, no second template."""
    builds = {item.preset: item for item in all_builds()}
    with_v6 = builds["desktop"].config
    without_v6 = builds["desktop-no-v6"].config

    assert "strategy" not in with_v6["dns"]
    assert without_v6["dns"].pop("strategy") == "ipv4_only"
    assert without_v6 == with_v6


def test_a_different_device_changes_only_device_facts() -> None:
    """Adding a device must not fork the policy. Only the declared facts may differ."""
    builds = {item.preset: item for item in all_builds()}
    desktop = json.loads(json.dumps(builds["desktop"].config))
    router = json.loads(json.dumps(builds["router"].config))

    assert router["inbounds"][0]["address"] == ["10.10.0.1/30", "fc00::10:10:0:1/126"]
    desktop["inbounds"][0]["address"] = router["inbounds"][0]["address"]

    # The control panel follows the allow_lan fact, which is the only other declared
    # difference between the two presets.
    api = "clash_api"
    assert router["experimental"][api]["external_controller"] == "0.0.0.0:9090"
    for key in ("external_controller", "access_control_allow_private_network"):
        desktop["experimental"][api][key] = router["experimental"][api][key]

    assert desktop == router


def test_every_capability_can_be_switched_off_cleanly() -> None:
    """Criterion 2, on the real library rather than on a fixture capability."""
    surface = Surface.load()
    for build in all_builds():
        assert comp.audit(surface, build) == []


def vmess_link(**overrides: object) -> str:
    """Build a v2ray-format link. Only the protocol fields matter here, not the link syntax,
    which `tests/test_protocols.py` pins down."""
    payload: dict[str, object] = {
        "v": "2",
        "ps": "vmess-node",
        "add": "203.0.113.30",
        "port": "443",
        "id": "b831381d-6324-4d53-ad4f-8cda48b30811",
        "aid": "0",
        "scy": "auto",
    }
    payload.update(overrides)
    return "vmess://" + base64.b64encode(json.dumps(payload).encode()).decode()


@requires_sing_box
def test_nodes_parsed_from_links_survive_the_binary(tmp_path: Path) -> None:
    """The last link in the chain: a subscription becomes a configuration sing-box accepts.

    The field surface can only say that a path exists. Whether the *values* a parser writes
    for a transport, a TLS block or a cipher are the ones sing-box wants is something only
    the binary can answer.
    """
    surface = Surface.load()
    document = preset_lib.load(PRESET_FILE)
    # Each node needs its own port: the deduplication key is protocol, host and port, so
    # four links to one endpoint would collapse into one node and test nothing.
    text = "\n".join(
        [
            "ss://YWVzLTEyOC1nY206ZXhhbXBsZQ@198.51.100.10:8388#Tokyo",
            vmess_link(net="ws", host="cdn.example.net", path="/ray", tls="tls"),
            vmess_link(
                port="8443", net="tcp", type="http", host="a.example.net,b.example.net"
            ),
            vmess_link(
                port="9443", net="grpc", path="service", tls="tls", sni="grpc.example.net"
            ),
            vmess_link(port="10443", net="kcp"),  # not implemented: must be skipped
        ]
    )

    feed = node_lib.collect([text])
    assert len(feed.nodes) == 4
    assert sum(feed.skipped.values()) == 1

    build = comp.compile_preset(
        surface, document.presets["desktop"], [item.as_dict() for item in feed.nodes]
    )
    target = tmp_path / "from-links.json"
    target.write_text(json.dumps(build.config, indent=2), encoding="utf-8")
    result = subprocess.run(
        sing_box_command("check", "-c", str(target)),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, f"sing-box check failed:\n{result.stdout}\n{result.stderr}"
