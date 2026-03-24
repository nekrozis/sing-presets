# Configuration for remote rulesets expansion
REMOTE_RULESETS = [
    "geosite-cn",
    "geosite-category-ads-all",
    "geoip-cn",
]

# VMess transport settings
MODIFY_VMESS_TRANSPORT = True
VMESS_HOST = "dldir1v6.qq.com"

def rule_set_to_dict(tag: str):
    # Split the tag into two parts at the first '-'
    parts = tag.split('-', 1)
    prefix = parts[0]
    
    if prefix == "geosite":
        url = f"https://cdn.jsdelivr.net/gh/SagerNet/sing-geosite@refs/heads/rule-set/{tag}.srs"
    elif prefix == "geoip":
        url = f"https://cdn.jsdelivr.net/gh/SagerNet/sing-geoip@refs/heads/rule-set/{tag}.srs"
    else:
        raise ValueError(f"Prefix must be 'geosite' or 'geoip', got: {prefix}")

    return {
        "type": "remote",
        "tag": tag,
        "format": "binary",
        "url": url,
        "download_detour": "direct"
    }
