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


def test_a_second_account_on_the_same_server_is_kept() -> None:
    """The same host and port with another password is another account, not a repeat."""
    feed = node_lib.collect(
        [link("Tokyo"), "ss://YWVzLTEyOC1nY206b3RoZXI@198.51.100.10:8388#Tokyo backup"]
    )
    assert [item.tag for item in feed.nodes] == ["Tokyo", "Tokyo backup"]
    assert feed.duplicates == 0


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


def test_a_source_may_be_a_link_itself() -> None:
    """A file of links passed where a list of sources is expected is an ordinary mistake.

    Reading `ss://...` as a relative path fails with `Invalid argument`, which names nothing
    and reads as if the link were at fault.
    """
    feed = node_lib.fetch([link("Tokyo")])
    assert [item.tag for item in feed.nodes] == ["Tokyo"]
    assert feed.failures == []


def test_a_source_that_is_neither_readable_nor_a_link_is_reported() -> None:
    feed = node_lib.fetch(["does-not-exist.txt", link("Tokyo")])
    assert [item.tag for item in feed.nodes] == ["Tokyo"]
    assert len(feed.failures) == 1
    assert feed.failures[0].startswith("does-not-exist.txt")


def test_a_subscription_token_is_not_written_down_or_printed() -> None:
    """A subscription URL carries its token, and both the record and the log are published.

    `nodes.json` is committed nowhere, but it is an artefact of a CI run, and a failure line
    goes to stderr - a log anyone on the project can read.
    """
    source = "https://panel.example.net/api/v1/client/subscribe?token=s3cret"
    assert node_lib.redact(source) == "https://panel.example.net"

    # Port 1 refuses at once, so this costs no network round trip and no waiting.
    unreachable = "http://127.0.0.1:1/api/v1/client/subscribe?token=s3cret"
    feed = node_lib.fetch([unreachable], timeout=1.0)
    assert feed.sources == ["http://127.0.0.1:1"]
    assert feed.failures, "an unreachable source should be reported"
    assert "s3cret" not in " ".join(feed.failures)
    assert "s3cret" not in json.dumps(feed.payload())


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
