from transform import *
import json

cfgs = generate_configs("../subscription.txt")

if __name__ == "__main__":
    print(",".join(json.dumps(cfg.to_singbox_config()) for cfg in cfgs))

    print("=" * 50)

    print(",".join(json.dumps(cfg.to_singbox_config()["tag"]) for cfg in cfgs))
