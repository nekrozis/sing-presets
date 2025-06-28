import base64
import requests
import re

SUPPORTED_PROTOCOLS = ["ss", "vmess"]


class ProxyLink:
    def __init__(self, protocol: str, content: str):
        self.protocol = protocol
        self.content = content

    def __repr__(self):
        return f"ProxyLink(protocol='{self.protocol}', content='{self.content}')"


def try_decode_base64(content: str) -> str | None:
    try:
        padding = 4 - (len(content) % 4)
        if padding != 4:
            content += "=" * padding
        decoded_bytes = base64.b64decode(content, validate=True)
        decoded_str = decoded_bytes.decode("utf-8")
        return decoded_str
    except Exception:
        return None


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


def main():
    links = fetch_and_extract_links("subscription.txt")
    for link in links:
        print(link)


if __name__ == "__main__":
    main()
