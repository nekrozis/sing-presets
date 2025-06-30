from dataclasses import dataclass
from parsers import protocol_parsers
import requests
import re
from .utils import *

SUPPORTED_PROTOCOLS = ["ss", "vmess"]


@dataclass
class ProxyLink:
    protocol: str
    content: str

    def __repr__(self):
        return f"ProxyLink(protocol='{self.protocol}', content='{self.content}')"


def extract_links_from_content(text: str) -> list[ProxyLink]:
    results = []
    lines = text.splitlines()
    # 根据SUPPORTED_PROTOCOLS构造正则协议部分
    proto_pattern = "|".join(SUPPORTED_PROTOCOLS)
    pattern = re.compile(rf"^({proto_pattern})://(.+)", re.IGNORECASE)

    for line in lines:
        line = line.strip()
        if not line:
            continue
        match = pattern.match(line)
        if match:
            protocol = match.group(1).lower()
            content = match.group(2)
            results.append(ProxyLink(protocol, content))
    return results


def fetch_and_extract_links(filepath: str) -> list[ProxyLink]:
    with open(filepath, "r", encoding="utf-8") as f:
        urls = [line.strip() for line in f if line.strip()]

    all_contents = []
    for url in urls:
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            content = response.text.strip()
            decoded = try_decode_base64(content)
            all_contents.append(decoded if decoded is not None else content)
        except Exception as e:
            print(f"Request failed: {url}, error: {e}")

    extracted = []
    for content in all_contents:
        extracted.extend(extract_links_from_content(content))
    return extracted


def generate_configs(subscription_file: str = "subscription.txt") -> list[dict]:
    links = fetch_and_extract_links(subscription_file)
    configs = []

    for link in links:
        parser = protocol_parsers.get(link.protocol)
        if not parser:
            print(f"Unsupported protocol: {link.protocol}")
            continue

        try:
            config = parser(link.content)
            configs.append(config)
        except Exception as e:
            print(f"Failed to parse {link}: {e}")

    return configs
