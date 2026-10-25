"""VMess links: a JSON object inside base64.

The awkward part is that a v2ray-format link describes the transport with two fields that
look interchangeable and are not. `net` names the transport, while `type` describes the
obfuscation applied *inside* the `tcp` transport, so:

    net=tcp             no transport at all
    net=tcp, type=http  HTTP obfuscation
    net=ws              websocket

Collapsing both into "http" - which the previous generator did - turns a plain TCP node into
one that cannot connect. The other direction matters too: sing-box has no `mkcp` and no
`xhttp`, so a link that asks for one is rejected with a reason instead of being emitted as
something that will not start.

`ps` is the display name in the link and becomes the node tag; a `#fragment` overrides it,
because that is the convention every other scheme uses.
"""

from __future__ import annotations

import json
from typing import Any

from ..protocol import LinkError, Node, Protocol, decode_base64, split_tag

#: v2ray `net` -> sing-box transport type. Missing entries are transports sing-box does not
#: implement; they are reported rather than silently dropped.
TRANSPORTS = {
    "ws": "ws",
    "http": "http",
    "h2": "http",
    "quic": "quic",
    "grpc": "grpc",
    "httpupgrade": "httpupgrade",
}

#: The values sing-box accepts for `security`.
SECURITY = frozenset(
    {"auto", "none", "zero", "aes-128-cfb", "aes-128-gcm", "chacha20-poly1305"}
)


def _int(value: Any, default: int = 0) -> int:
    """Read an integer that a link may well have written as a string."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _text(data: dict, key: str) -> str:
    return str(data.get(key, "") or "").strip()


class VMess(Protocol):
    scheme = "vmess"

    def parse(self, payload: str) -> Node:
        payload, tag = split_tag(payload)
        decoded = decode_base64(payload)
        if decoded is None:
            raise LinkError("vmess payload is not base64")
        try:
            data = json.loads(decoded)
        except json.JSONDecodeError as error:
            raise LinkError(f"vmess payload is not JSON: {error}") from error
        if not isinstance(data, dict):
            raise LinkError("vmess payload is not an object")

        body: dict[str, Any] = {
            "type": "vmess",
            "server": _text(data, "add"),
            "server_port": _int(data.get("port")),
            "uuid": _text(data, "id"),
            "security": self._security(data),
        }
        transport = self._transport(data)
        if transport:
            body["transport"] = transport
        tls = self._tls(data)
        if tls:
            body["tls"] = tls
        return self.node(tag or _text(data, "ps"), body)

    @staticmethod
    def _security(data: dict) -> str:
        """`scy` names the cipher; anything unrecognised falls back to `auto`.

        `auto` is not a fallback in the "give up" sense: it is what the protocol negotiates
        by default, and it makes sing-box pick a cipher both ends support.
        """
        value = _text(data, "scy").lower()
        return value if value in SECURITY else "auto"

    @staticmethod
    def _transport(data: dict) -> dict[str, Any]:
        network = _text(data, "net").lower()
        obfuscation = _text(data, "type").lower()
        host = _text(data, "host")
        path = _text(data, "path")
        service = _text(data, "serviceName")

        if network in ("", "tcp", "raw"):
            if obfuscation != "http":
                return {}
            network = "http"

        kind = TRANSPORTS.get(network)
        if kind is None:
            raise LinkError(f"vmess transport {network!r} is not supported by sing-box")

        transport: dict[str, Any] = {"type": kind}
        if kind == "http":
            if host:
                # Several host header values, comma separated in the link.
                transport["host"] = [item.strip() for item in host.split(",") if item.strip()]
            if path:
                transport["path"] = path
        elif kind == "ws":
            if path:
                transport["path"] = path
            if host:
                # A websocket handshake carries the host as a header, not as a field.
                transport["headers"] = {"Host": host}
        elif kind == "grpc":
            if service or path:
                transport["service_name"] = service or path.lstrip("/")
        elif kind == "httpupgrade":
            if host:
                transport["host"] = host
            if path:
                transport["path"] = path
        return transport

    @staticmethod
    def _tls(data: dict) -> dict[str, Any]:
        if _text(data, "tls").lower() != "tls":
            return {}
        tls: dict[str, Any] = {"enabled": True}
        # `sni` wins, then the host: for a TLS transport the host is the server name unless
        # the link says otherwise. A host list is not a server name, so the first entry wins.
        name = _text(data, "sni") or _text(data, "host")
        if name:
            tls["server_name"] = name.split(",")[0].strip()
        alpn = _text(data, "alpn")
        if alpn:
            tls["alpn"] = [item.strip() for item in alpn.split(",") if item.strip()]
        fingerprint = _text(data, "fp")
        if fingerprint:
            tls["utls"] = {"enabled": True, "fingerprint": fingerprint}
        return tls
