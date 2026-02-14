# Sing-box Configuration Preset Repository

A small Python project that generates sing-box configuration files from subscription URLs using a base YAML template.

## Quick Start

```bash
# 1. Clone this repository
git clone git@github.com:<your-username>/sing-presets.git
cd sing-presets

# 2. Create subscription.txt in the repository root
nano subscription.txt

# 3. Run the configuration generator from the scripts directory
cd scripts
python main.py
```

After running the script, these files are created in the repository root:

- `config.json`
- `config-api.json`

## Subscription File

Create a `subscription.txt` file in the repository root with subscription URLs, one per line:

```
https://example.com/subscription1
https://example.com/subscription2
```

Each non-empty line must be a URL. Comments are not supported. The script will:

1. Fetch content from each subscription URL
2. Decode base64-encoded content when possible
3. Extract proxy links that start with `ss://` or `vmess://` (case-insensitive)
4. Parse the proxies into sing-box outbound entries

## Base Template

The `base.yaml` file contains the default sing-box configuration template, including:

- Logging settings
- DNS servers and rules
- TUN inbound configuration
- Selector and urltest outbounds
- Routing rules with GeoSite and GeoIP rule sets

Generated proxies are inserted into the template using `_PROXY_NODES_` and `_PROXY_TAGS_` placeholders.

## Feature Modules

Feature fragments are located in the `features/` directory:

- `clash_api.yaml`: Clash API settings used by `scripts/main.py` to build `config-api.json`
- `clash_api_allow_private.yaml`: Alternative Clash API settings that allow private network access; not used by default

## Project Structure

- `base.yaml`: Base configuration template
- `features/`: Feature fragments
- `scripts/`: Configuration generation scripts
  - `main.py`: Entry point for configuration generation
  - `transform.py`: Subscription fetching and proxy extraction
  - `parsers/`: Protocol-specific parsers for Shadowsocks and VMess

## Requirements

- Python 3.9 or higher
- PyYAML
- requests

