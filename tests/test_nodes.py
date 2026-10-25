"""The feed: what a subscription becomes before the compiler sees it.

Three behaviours matter here, and all three were missing from the previous pipeline:

  - links that cannot be parsed are counted with a reason instead of printed and forgotten,
  - the same server is kept once, whatever it is called,
  - a tag collision is resolved rather than left to fail inside sing-box, where the message
    names an outbound the user never wrote.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

from sing_presets import nodes as node_lib
from sing_presets.protocol import Node

SS = "ss://YWVzLTEyOC1nY206ZXhhbXBsZQ@198.51.100.10:8388#{tag}"


def link(tag: str) -> str:
    return SS.format(tag=tag)


def node(tag: str, host: str = "198.51.100.10", port: int = 8388) -> Node:
    return Node(
        tag=tag,
        outbound={
            "type": "shadowsocks",
            "server": host,
            "server_port": port,
            "method": "aes-128-gcm",
            "password": "example",
        },
    )


def test_only_link_lines_are_extracted() -> None:
    text = "\n".join(
        [
            "# a comment",
            "",
            "  " + link("Tokyo") + "  ",
            "not a link at all",
            "https://example.net/sub",
        ]
    )
    assert node_lib.extract_links(text) == [link("Tokyo"), "https://example.net/sub"]


def test_a_display_name_may_contain_spaces() -> None:
    """Names like "Tokyo 01" are the norm; requiring a line without spaces drops them."""
    assert node_lib.extract_links(link("Tokyo 01")) == [link("Tokyo 01")]


def test_the_same_server_is_kept_once_whatever_its_name() -> None:
    feed = node_lib.collect([link("Tokyo"), link("Tokyo again")])
    assert [item.tag for item in feed.nodes] == ["Tokyo"]
    assert feed.duplicates == 1


def test_a_different_port_is_a_different_server() -> None:
    feed = node_lib.collect([link("A"), SS.replace(":8388", ":8389").format(tag="B")])
    assert len(feed.nodes) == 2


def test_a_broken_link_is_counted_with_its_reason() -> None:
    feed = node_lib.collect([link("Good"), "vmess://not-base64-at-all", "kcp://example"])
    assert [item.tag for item in feed.nodes] == ["Good"]
    assert sum(feed.skipped.values()) == 2
    assert any("no parser for scheme 'kcp'" in reason for reason in feed.skipped)


def test_a_duplicate_name_gains_a_suffix() -> None:
    tags = [item.tag for item in node_lib.unique_tags([node("Tokyo"), node("Tokyo")])]
    assert tags == ["Tokyo", "Tokyo (2)"]


def test_a_node_may_not_take_a_group_tag() -> None:
    """`proxy` is the selector; a node with that name would collide with it."""
    tags = [item.tag for item in node_lib.unique_tags([node("proxy"), node("auto")])]
    assert tags == ["proxy (2)", "auto (2)"]


def test_a_source_may_be_a_file_and_may_be_base64(tmp_path: Path) -> None:
    """Both shapes are handed out by panels; the URL does not say which one it is."""
    plain = tmp_path / "plain.txt"
    wrapped = tmp_path / "wrapped.txt"
    plain.write_text(link("A") + "\n", encoding="utf-8")
    wrapped.write_text(
        base64.b64encode((link("B") + "\n").encode()).decode(), encoding="utf-8"
    )
    assert node_lib.extract_links(node_lib.read_source(str(plain))) == [link("A")]
    assert node_lib.extract_links(node_lib.read_source(str(wrapped))) == [link("B")]


def test_the_payload_is_what_the_build_reads(tmp_path: Path) -> None:
    """`build --nodes` reads `{"nodes": [...]}`, each entry an outbound with a tag."""
    feed = node_lib.collect([link("Tokyo")])
    target = node_lib.write(feed, tmp_path / "nodes.json")
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["nodes"] == [
        {
            "tag": "Tokyo",
            "type": "shadowsocks",
            "server": "198.51.100.10",
            "server_port": 8388,
            "method": "aes-128-gcm",
            "password": "example",
        }
    ]
