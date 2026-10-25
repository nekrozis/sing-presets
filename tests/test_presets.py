"""The preset document: it is the file a user edits, so its mistakes must be legible.

Every test here is about a typo being reported as a typo. A preset document that silently
ignores an unknown key is worse than one that refuses to load, because the user keeps
believing the setting took effect.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sing_presets import presets as preset_lib

HEADER = """
defaults:
  facts: {log.level: info, device.mtu: 1500}
  capabilities: [logging, tun-inbound, dns-split, outbound-groups]
presets:
"""


def load(tmp_path: Path, body: str) -> preset_lib.PresetFile:
    path = tmp_path / "presets.yaml"
    path.write_text(HEADER + body, encoding="utf-8")
    return preset_lib.load(path)


def test_a_preset_inherits_the_defaults(tmp_path: Path) -> None:
    document = load(
        tmp_path,
        """
  one:
    facts: {device.tun_address: ["172.18.0.1/30"]}
""",
    )
    preset = document.presets["one"]
    assert preset.facts == {"log.level": "info", "device.mtu": 1500,
                            "device.tun_address": ["172.18.0.1/30"]}
    assert preset.capabilities == ("logging", "tun-inbound", "dns-split", "outbound-groups")


def test_a_preset_overrides_a_single_fact(tmp_path: Path) -> None:
    document = load(
        tmp_path,
        """
  one:
    facts: {device.mtu: 9000}
""",
    )
    assert document.presets["one"].facts["device.mtu"] == 9000
    assert document.presets["one"].facts["log.level"] == "info"


def test_extends_carries_facts_and_capabilities(tmp_path: Path) -> None:
    document = load(
        tmp_path,
        """
  base:
    facts: {device.tun_address: ["172.18.0.1/30"], network.allow_lan: false}
  variant:
    extends: base
    capabilities_add: [cache-file]
    facts: {network.allow_lan: true}
""",
    )
    variant = document.presets["variant"]
    assert variant.facts == {
        "log.level": "info",
        "device.mtu": 1500,
        "device.tun_address": ["172.18.0.1/30"],
        "network.allow_lan": True,
    }
    assert "cache-file" in variant.capabilities
    assert len(document.presets["base"].capabilities) == 4


def test_extends_an_unknown_preset(tmp_path: Path) -> None:
    with pytest.raises(preset_lib.PresetError, match="extends unknown preset"):
        load(
            tmp_path,
            """
  one:
    extends: nowhere
""",
        )


def test_inheritance_loop_is_reported_with_the_chain(tmp_path: Path) -> None:
    with pytest.raises(preset_lib.PresetError, match="loops: a -> b -> a"):
        load(
            tmp_path,
            """
  a: {extends: b}
  b: {extends: a}
""",
        )


def test_an_unknown_capability_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(preset_lib.PresetError, match="unknown capability"):
        load(
            tmp_path,
            """
  one:
    capabilities_add: [no-such-capability]
""",
        )


def test_an_unknown_preset_key_is_rejected(tmp_path: Path) -> None:
    """A misspelled key would otherwise be ignored and the setting silently skipped."""
    with pytest.raises(preset_lib.PresetError, match="unknown keys"):
        load(
            tmp_path,
            """
  one:
    facts: {device.mtu: 9000}
    capability_add: [cache-file]
""",
        )


def test_an_unknown_top_level_key_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "presets.yaml"
    path.write_text("presets: {}\ndefault: {}\n", encoding="utf-8")
    with pytest.raises(preset_lib.PresetError):
        preset_lib.load(path)


def test_a_fact_name_must_be_dotted(tmp_path: Path) -> None:
    with pytest.raises(preset_lib.PresetError, match="must be a dotted name"):
        load(
            tmp_path,
            """
  one:
    facts: {mtu: 9000}
""",
        )


def test_removing_a_capability_that_is_not_there_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(preset_lib.PresetError, match="cannot remove"):
        load(
            tmp_path,
            """
  one:
    capabilities_remove: [cache-file]
""",
        )


def test_capabilities_can_be_replaced_outright(tmp_path: Path) -> None:
    document = load(
        tmp_path,
        """
  one:
    capabilities: [logging]
""",
    )
    assert document.presets["one"].capabilities == ("logging",)


def test_a_document_without_presets_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "presets.yaml"
    path.write_text("defaults: {}\n", encoding="utf-8")
    with pytest.raises(preset_lib.PresetError, match="defines no presets"):
        preset_lib.load(path)
