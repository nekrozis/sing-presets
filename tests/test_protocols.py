"""Share-link parsing: what each scheme turns into, and what it refuses.

The links here are fixed strings rather than values assembled in the test. The point is to
pin the interpretation of a link as it appears in the wild; a test that builds its own input
would keep passing after the parser stopped understanding real ones.

Most of these are about the parts that are easy to get wrong: where the credentials hide in
an `ss` link, and the difference between `net` and `type` in a `vmess` link.
"""

from __future__ import annotations

import base64
import json

import pytest

from sing_presets.protocol import LinkError, parse_link

# ss://base64("aes-128-gcm:example")@198.51.100.10:8388#Tokyo  (SIP002)
SS_SIP002 = "ss://YWVzLTEyOC1nY206ZXhhbXBsZQ@198.51.100.10:8388#Tokyo"

# ss://base64("aes-256-gcm:secret@198.51.100.11:8389")  (the older fully encoded form)
SS_LEGACY = "ss://YWVzLTI1Ni1nY206c2VjcmV0QDE5OC41MS4xMDAuMTE6ODM4OQ"

# The same SIP002 link with an obfs plugin, which is one query parameter with its own
# semicolon-separated options.
SS_PLUGIN = (
    "ss://YWVzLTEyOC1nY206ZXhhbXBsZQ@198.51.100.12:8388/"
    "?plugin=obfs-local%3Bobfs%3Dhttp%3Bobfs-host%3Dbing.com#Plugin"
)

# vmess://base64({ps: Osaka, add, port 443, net ws, tls with sni/alpn/fp})
VMESS_WS = (
    "vmess://eyJ2IjoiMiIsInBzIjoiT3Nha2EiLCJhZGQiOiIxOTguNTEuMTAwLjIwIiwicG9ydCI6IjQ0MyIs"
    "ImlkIjoiYjgzMTM4MWQtNjMyNC00ZDUzLWFkNGYtOGNkYTQ4YjMwODExIiwiYWlkIjoiMCIsInNjeSI6"
    "ImF1dG8iLCJuZXQiOiJ3cyIsInR5cGUiOiJub25lIiwiaG9zdCI6ImNkbi5leGFtcGxlLm5ldCIsInBh"
    "dGgiOiIvcmF5IiwidGxzIjoidGxzIiwic25pIjoiY2RuLmV4YW1wbGUubmV0IiwiYWxwbiI6ImgyLGh0"
    "dHAvMS4xIiwiZnAiOiJjaHJvbWUifQ"
)

# vmess://base64({ps: Plain, net tcp, type http, two hosts, scy AES-128-GCM, aid 64})
VMESS_TCP_HTTP = (
    "vmess://eyJ2IjoiMiIsInBzIjoiUGxhaW4iLCJhZGQiOiIxOTguNTEuMTAwLjIxIiwicG9ydCI6ODA4"
    "MCwiaWQiOiJiODMxMzgxZC02MzI0LTRkNTMtYWQ0Zi04Y2RhNDhiMzA4MTEiLCJhaWQiOiI2NCIsInNj"
    "eSI6IkFFUy0xMjgtR0NNIiwibmV0IjoidGNwIiwidHlwZSI6Imh0dHAiLCJob3N0IjoiYS5leGFtcGxl"
    "Lm5ldCxiLmV4YW1wbGUubmV0IiwicGF0aCI6Ii9vYmZzIn0"
)

# vmess://base64({ps: Bare, net tcp, type none})
VMESS_BARE_TCP = (
    "vmess://eyJ2IjoiMiIsInBzIjoiQmFyZSIsImFkZCI6IjE5OC41MS4xMDAuMjIiLCJwb3J0IjoiOTAw"
    "MCIsImlkIjoiYjgzMTM4MWQtNjMyNC00ZDUzLWFkNGYtOGNkYTQ4YjMwODExIiwiYWlkIjoiMCIsInNj"
    "eSI6ImF1dG8iLCJuZXQiOiJ0Y3AiLCJ0eXBlIjoibm9uZSJ9"
)

# vmess://base64({ps: Grpc, net grpc, path svc, tls})
VMESS_GRPC = (
    "vmess://eyJ2IjoiMiIsInBzIjoiR3JwYyIsImFkZCI6IjE5OC41MS4xMDAuMjMiLCJwb3J0IjoiNDQz"
    "IiwiaWQiOiJiODMxMzgxZC02MzI0LTRkNTMtYWQ0Zi04Y2RhNDhiMzA4MTEiLCJhaWQiOiIwIiwic2N5"
    "IjoiYXV0byIsIm5ldCI6ImdycGMiLCJwYXRoIjoic3ZjIiwidGxzIjoidGxzIiwic25pIjoiZy5leGFt"
    "cGxlLm5ldCJ9"
)

# vmess://base64({ps: Kcp, net kcp}) - a transport sing-box does not implement
VMESS_KCP = (
    "vmess://eyJ2IjoiMiIsInBzIjoiS2NwIiwiYWRkIjoiMTk4LjUxLjEwMC4yNCIsInBvcnQiOiI0NDMi"
    "LCJpZCI6ImI4MzEzODFkLTYzMjQtNGQ1My1hZDRmLThjZGE0OGIzMDgxMSIsIm5ldCI6ImtjcCJ9"
)


def _vmess_with_path(path: str) -> str:
    """A WebSocket link whose only difference from its sibling is the path."""
    payload = {
        "v": "2",
        "ps": "Hong Kong",
        "add": "198.51.100.30",
        "port": "8080",
        "id": "b831381d-6324-4d53-ad4f-8cda48b30811",
        "aid": "0",
        "scy": "auto",
        "net": "ws",
        "type": "none",
        "host": "cdn.example.net",
        "path": path,
        "tls": "tls",
    }
    return "vmess://" + base64.b64encode(json.dumps(payload).encode()).decode()


def test_sip002_link_keeps_the_host_readable_and_the_tag_in_the_fragment() -> None:
    node = parse_link(SS_SIP002)
    assert node.tag == "Tokyo"
    assert node.outbound == {
        "type": "shadowsocks",
        "server": "198.51.100.10",
        "server_port": 8388,
        "method": "aes-128-gcm",
        "password": "example",
    }


def test_legacy_link_encodes_the_whole_endpoint() -> None:
    node = parse_link(SS_LEGACY)
    assert node.outbound["server"] == "198.51.100.11"
    assert node.outbound["server_port"] == 8389
    assert node.outbound["method"] == "aes-256-gcm"
    assert node.outbound["password"] == "secret"
    # No fragment, so the tag is derived from the endpoint rather than a random id: the
    # build has to be reproducible.
    assert node.tag == "shadowsocks-198.51.100.11:8389"


def test_the_shadowsocks_plugin_becomes_a_name_and_its_own_options() -> None:
    outbound = parse_link(SS_PLUGIN).outbound
    assert outbound["plugin"] == "obfs-local"
    assert outbound["plugin_opts"] == "obfs=http;obfs-host=bing.com"


def test_an_ss_link_without_credentials_is_refused() -> None:
    with pytest.raises(LinkError, match="no usable method or password"):
        parse_link("ss://:8388")


def test_vmess_websocket_carries_the_host_as_a_header() -> None:
    outbound = parse_link(VMESS_WS).outbound
    assert outbound["transport"] == {
        "type": "ws",
        "path": "/ray",
        "headers": {"Host": "cdn.example.net"},
    }


def test_vmess_tls_is_only_written_when_the_link_asks_for_it() -> None:
    assert parse_link(VMESS_WS).outbound["tls"] == {
        "enabled": True,
        "server_name": "cdn.example.net",
        "alpn": ["h2", "http/1.1"],
        "utls": {"enabled": True, "fingerprint": "chrome"},
    }
    assert "tls" not in parse_link(VMESS_BARE_TCP).outbound


def test_tcp_with_http_obfuscation_is_a_transport_and_a_bare_tcp_is_not() -> None:
    """`net` names the transport, `type` describes the obfuscation inside it."""
    obfuscated = parse_link(VMESS_TCP_HTTP).outbound
    assert obfuscated["transport"] == {
        "type": "http",
        "host": ["a.example.net", "b.example.net"],
        "path": "/obfs",
    }
    assert "transport" not in parse_link(VMESS_BARE_TCP).outbound


def test_vmess_security_is_lower_cased() -> None:
    assert parse_link(VMESS_TCP_HTTP).outbound["security"] == "aes-128-gcm"


def test_an_unrecognised_vmess_cipher_falls_back_to_auto() -> None:
    """`auto` is what the protocol negotiates by default, so it is the safe read."""
    payload = base64.b64encode(
        json.dumps({"ps": "x", "add": "198.51.100.30", "port": 443, "id": "u",
                    "scy": "rc4"}).encode()
    ).decode()
    assert parse_link(f"vmess://{payload}").outbound["security"] == "auto"


def test_grpc_takes_its_service_name_from_the_path() -> None:
    assert parse_link(VMESS_GRPC).outbound["transport"] == {
        "type": "grpc",
        "service_name": "svc",
    }


def test_a_transport_sing_box_does_not_have_is_refused_with_a_reason() -> None:
    with pytest.raises(LinkError, match="'kcp' is not supported"):
        parse_link(VMESS_KCP)


def test_an_unknown_scheme_lists_what_is_known() -> None:
    with pytest.raises(LinkError, match="no parser for scheme 'hysteria2'"):
        parse_link("hysteria2://example")


def test_a_port_that_is_not_a_number_is_reported_not_raised() -> None:
    """A subscription is full of broken links; one must not stop the others."""
    with pytest.raises(LinkError, match="cannot be parsed"):
        parse_link("ss://YWVzLTEyOC1nY206ZXhhbXBsZQ@198.51.100.10:not-a-port")


def test_a_second_account_on_one_server_is_a_second_node() -> None:
    """Credentials are part of what a node is: another password is another account."""
    first = parse_link(SS_SIP002)
    second = parse_link("ss://YWVzLTEyOC1nY206b3RoZXI@198.51.100.10:8388#Other")
    assert first.dedup_key != second.dedup_key
    assert first.tag != second.tag


def test_two_paths_on_one_host_and_port_are_two_nodes() -> None:
    """Host and port do not identify a node.

    A panel can front a list of exits through one host and one port and tell the customers
    apart by nothing but the path of their WebSocket transport. A live 41-link subscription
    of that shape turned into two nodes under the old key, and 39 the binary would have
    accepted were dropped without a word.
    """
    first = parse_link(_vmess_with_path("/ray"))
    second = parse_link(_vmess_with_path("/ray2"))
    assert first.outbound["server"] == second.outbound["server"]
    assert first.outbound["server_port"] == second.outbound["server_port"]
    assert first.dedup_key != second.dedup_key
