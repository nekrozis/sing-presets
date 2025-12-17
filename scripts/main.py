from transform import *
import json
import yaml

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
    cfg = json.dumps(cfg, ensure_ascii=False, indent=2)
    print(cfg)
    with open("../config.json", "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

    with open("../features/clash_api.yaml") as f:
        clash_yml = yaml.safe_load(f)

    cfg_with_api = replace_macros(base_yml)
    cfg_with_api["experimental"]["clash_api"] = clash_yml["experimental"]["clash_api"]

    with open("../config-api.json", "w", encoding="utf-8") as f:
        json.dump(cfg_with_api, f, ensure_ascii=False, indent=2)
