from dataclasses import dataclass
from typing import Optional
import uuid
from ..utils import *
import json


@dataclass
class VMess:
    ps: str
    add: str
    port: str
    id: str
    aid: str
    scy: str
    net: str
    type: str
    host: Optional[str] = None
    path: Optional[str] = None
    tls: Optional[str] = None
    sni: Optional[str] = None
    alpn: Optional[str] = None
    fp: Optional[str] = None

    def to_singbox_config(self) -> dict:
        """转换为 sing-box 节点配置"""
        config = {
            "type": "vmess",
            "tag": self.ps,
            "server": self.add,
            "server_port": int(self.port),
            "uuid": self.id,
            # "alter_id": int(self.aid) if self.aid.isdigit() else 0,
            "alter_id": 0,
            # "security": self.scy,
            "security": "aes-128-gcm",
        }

        if self.net:
            transport = {}
            if self.net == "tcp" or self.net == "h2":
                transport["type"] = "http"
                # if self.host:
                #     transport["host"] = self.host.split(",")
                # if self.path:
                #     transport["path"] = self.path
                transport["host"] = ["dldir1v6.qq.com"]
                transport["path"] = "/"
            elif self.net == "ws":
                transport["type"] = "ws"
                if self.path:
                    transport["path"] = self.path
            elif self.net == "quic":
                transport["type"] = "quic"
            elif self.net == "kcp":
                raise NotImplementedError("kcp transport is not supported yet.")
            config["transport"] = transport
        
        if self.tls and self.tls.lower() == "tls":
            tls_config = {"enabled": True}
            tls_config["server_name"] = self.sni
            if self.alpn:
                tls_config["alpn"] = self.alpn.split(",")
            if self.fp:
                tls_config["utls"] = {
                    "enabled": True,
                    "fingerprint": self.fp
                }
            config["tls"] = tls_config

        return config


def parse_vmess(link: str) -> Optional[VMess]:

    decoded = try_decode_base64(link)
    if not decoded:
        return None

    try:
        data: dict = json.loads(decoded)
    except json.JSONDecodeError:
        return None

    return VMess(
        ps=data.get("ps", f"ss-{uuid.uuid4().hex[:8]}"),
        add=data.get("add", ""),
        port=str(data.get("port", "")),
        id=data.get("id", ""),
        aid=str(data.get("aid", "0")),
        scy=data.get("scy", "auto"),
        net=data.get("net", ""),
        type=data.get("type", ""),
        host=data.get("host"),
        path=data.get("path"),
        tls=data.get("tls"),
        sni=data.get("sni"),
        alpn=data.get("alpn"),
        fp=data.get("fp"),
    )
