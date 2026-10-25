from dataclasses import dataclass
from typing import Optional
from urllib.parse import parse_qs, unquote, urlparse
from utils import *
import uuid


@dataclass
class Shadowsocks:
    server: str
    port: int
    method: str
    password: str
    tag: str
    plugin: Optional[str] = None
    plugin_opts: Optional[str] = None

    def to_singbox_config(self) -> dict:
        cfg = {
            "type": "shadowsocks",
            "tag": self.tag,
            "server": self.server,
            "server_port": self.port,
            "method": self.method,
            "password": self.password,
        }

        if self.plugin:
            cfg["plugin"] = self.plugin
            if self.plugin_opts:
                cfg["plugin_opts"] = self.plugin_opts

        return cfg


def parse_ss(link: str) -> Optional[Shadowsocks]:
    link = link.strip()
    if not link:
        return None

    tag = ""
    if "#" in link:
        link, tag = link.rsplit("#", 1)
        tag = unquote(tag)
    else:
        tag = f"ss-{uuid.uuid4().hex[:8]}"

    # ss://base64(method:password@host:port?plugin=xxx)
    if (decoded := try_decode_base64(link)) is not None:
        link = decoded

    # ss://base64(method:password)@host:port?plugin=xxx
    # ss://method:password@host:port?plugin=xxx
    u = urlparse(f"ss://{link}")

    # urlparse returns None for any component the link does not carry. A malformed link
    # has to be rejected here, otherwise the node is built with empty credentials and
    # only fails much later, inside sing-box.
    username = u.username or ""
    method = ""
    password = ""
    if (decoded := try_decode_base64(username)) is not None:
        if ":" not in decoded:
            raise ValueError(f"ss credentials are not in method:password form: {decoded!r}")
        method, password = decoded.split(":", 1)
    else:
        method = username
        password = u.password or ""

    server = u.hostname or ""
    port = u.port

    if not server or port is None:
        raise ValueError(f"ss link has no usable server or port: {link!r}")
    if not method or not password:
        raise ValueError(f"ss link has no usable method or password: {link!r}")

    plugin = None
    plugin_opts = None
    q = parse_qs(u.query)
    plugin_raw = q.get("plugin", [])
    if plugin_raw:
        plugin_parts = plugin_raw[0].split(";")
        if plugin_parts:
            plugin = plugin_parts[0]
            plugin_opts = ";".join(plugin_parts[1:]) if len(plugin_parts) > 1 else ""

    return Shadowsocks(
        server=server,
        port=port,
        method=method,
        password=password,
        tag=tag,
        plugin=plugin,
        plugin_opts=plugin_opts,
    )
