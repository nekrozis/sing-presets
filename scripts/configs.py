import os

# Configuration for remote rulesets expansion
REMOTE_RULESETS = [
    "geosite-cn",
    "geosite-category-ads-all",
    "geoip-cn",
]

# VMess transport settings
MODIFY_VMESS_TRANSPORT = True
VMESS_HOST = "mmbiz.qpic.cn"

# Clash API and Connectivity settings
GENERATE_CLASH_API = True
ALLOW_LAN = False
USE_ENV_FOR_SECRET = False
CLASH_SECRET = "midnight-espresso"

def get_clash_api_config():
    """Returns the clash_api dictionary based on current settings."""
    secret = os.environ.get(CLASH_SECRET, "") if USE_ENV_FOR_SECRET else CLASH_SECRET
    
    return {
        "external_controller": "0.0.0.0:9090" if ALLOW_LAN else "127.0.0.1:9090",
        "external_ui": "dashboard",
        "external_ui_download_url": "https://github.com/MetaCubeX/metacubexd/archive/refs/heads/gh-pages.zip",
        "secret": secret,
        "access_control_allow_private_network": ALLOW_LAN
    }

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
