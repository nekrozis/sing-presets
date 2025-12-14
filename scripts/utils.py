import base64


def try_decode_base64(content: str) -> str | None:
    content = content.strip()
    padding = len(content) % 4
    if padding != 0:
        content += "=" * (4 - padding)

    try:
        if "-" in content or "_" in content:
            decoded_bytes = base64.urlsafe_b64decode(content)
        else:
            decoded_bytes = base64.b64decode(content, validate=True)
        return decoded_bytes.decode("utf-8")
    except Exception:
        return None
