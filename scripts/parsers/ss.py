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
        config = {
            "type": "shadowsocks",
            "tag": self.tag,
            "server": self.server,
            "server_port": self.port,
            "method": self.method,
            "password": self.password,
        }

        if self.plugin:
            config["plugin"] = self.plugin
            if self.plugin_opts:
                config["plugin_opts"] = self.plugin_opts

        return config


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
    method = ""
    password = ""

    if (decoded := try_decode_base64(u.username)) is not None:
        method, password = decoded.split(":", 1)
    else:
        method = u.username
        password = u.password

    server = u.hostname
    port = u.port

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
