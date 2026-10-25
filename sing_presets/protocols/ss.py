"""Shadowsocks links: the SIP002 form and the older fully-encoded one.

The two forms differ only in where the credentials live. SIP002 keeps the host readable and
encodes `method:password` as the userinfo; the older form encodes the whole
`method:password@host:port` and puts the plugin in a query string. Both are still handed
out, so both are accepted.

The plugin string is passed through unchanged. sing-box understands `obfs-local` and
`v2ray-plugin` option strings as they appear in the link, and rewriting them here would only
drop the settings this code does not know about.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import unquote, urlparse

from ..protocol import LinkError, Node, Protocol, decode_base64, query_parameters, split_tag


class Shadowsocks(Protocol):
    scheme = "ss"

    def parse(self, payload: str) -> Node:
        payload, tag = split_tag(payload)

        # A payload that decodes to something containing "@" is the whole endpoint encoded;
        # one that does not is SIP002, where only the credentials are encoded. Trying the
        # decode first distinguishes them without guessing.
        decoded = decode_base64(payload)
        if decoded is not None and "@" in decoded:
            payload = decoded

        url = urlparse(f"ss://{payload}")
        method, password = self._credentials(url)
        if not method or not password:
            raise LinkError("ss link has no usable method or password")
        body: dict[str, Any] = {
            "type": "shadowsocks",
            "server": url.hostname or "",
            "server_port": url.port,
            "method": method,
            "password": password,
            **self._plugin(url.query),
        }
        return self.node(tag, body)

    @staticmethod
    def _credentials(url: Any) -> tuple[str, str]:
        """Split the userinfo into method and password, whichever form it is in.

        SIP002 encodes `method:password`, the older form leaves them as two fields. A decode
        without a colon means the userinfo was not credentials at all - a cipher name can be
        valid base64 by accident - so it is read as the method instead.

        Nothing here echoes the decoded value in an error: it is the password.
        """
        userinfo = unquote(url.username or "")
        decoded = decode_base64(userinfo)
        if decoded is not None and ":" in decoded:
            method, _, password = decoded.partition(":")
            return method, password
        return userinfo, unquote(url.password or "")

    @staticmethod
    def _plugin(query: str) -> dict[str, Any]:
        """`plugin=obfs-local;obfs=http;obfs-host=...` is a name plus its own options."""
        raw = query_parameters(query).get("plugin", "")
        if not raw:
            return {}
        name, separator, options = raw.partition(";")
        if not separator:
            return {"plugin": name}
        return {"plugin": name, "plugin_opts": options}
