from transform import *
import json
import yaml
import configs

if __name__ == "__main__":
    # 1. Generate configs
    cfgs = generate_configs("../subscription.txt")

    proxy_nodes = [cfg.to_singbox_config() for cfg in cfgs]
    proxy_tags = [cfg.to_singbox_config()["tag"] for cfg in cfgs]

    # 2. Load base template
    with open("../base.yaml", "r", encoding="utf-8") as f:
        base_yml = yaml.safe_load(f)

    macros = {
        "_PROXY_NODES_": proxy_nodes,
        "_PROXY_TAGS_": proxy_tags,
        "_REMOTE_RULESETS_": [configs.rule_set_to_dict(rs) for rs in configs.REMOTE_RULESETS],
    }

    def replace_macros(node):
        if isinstance(node, list):
            new_list = []
            for item in node:
                replaced = replace_macros(item)
                if (
                    isinstance(item, str)
                    and item in macros
                    and isinstance(replaced, list)
                ):
                    new_list.extend(replaced)
                else:
                    new_list.append(replaced)
            return new_list
        elif isinstance(node, dict):
            return {k: replace_macros(v) for k, v in node.items()}
        elif isinstance(node, str):
            if node in macros:
                return macros[node]
            return node
        else:
            return node

    cfg = replace_macros(base_yml)
    print("Generating config.json...")
    with open("../config.json", "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

    if configs.GENERATE_CLASH_API:
        print("Generating config-web_ui.json with Web UI...")
        clash_api_config = configs.get_clash_api_config()

        # Create a copy and add the experimental/clash_api key
        cfg_with_api = cfg.copy()
        experimental = cfg_with_api.get("experimental", {}).copy()
        experimental["clash_api"] = clash_api_config
        cfg_with_api["experimental"] = experimental

        with open("../config-web_ui.json", "w", encoding="utf-8") as f:
            json.dump(cfg_with_api, f, ensure_ascii=False, indent=2)
