import base64


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
