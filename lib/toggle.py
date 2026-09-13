#!/usr/bin/env python3
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_config, save_config  # noqa: E402

SECTIONS = ("fans", "desk", "govee", "keyboard")


def main(target, want=""):
    cfg = load_config()
    if target.startswith("govee:"):
        node = cfg["govee"].setdefault("devices", {}).setdefault(target.split(":", 1)[1], {})
    elif target in SECTIONS:
        node = cfg[target]
    else:
        print("unknown device: %s (try: %s, govee:<id>)" % (target, ", ".join(SECTIONS)), file=sys.stderr)
        return 1
    node["enabled"] = {"on": True, "off": False}.get(want, not node.get("enabled", True))
    save_config(cfg)
    print("%s %s" % (target, "on" if node["enabled"] else "off"))
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: toggle.py <id> [on|off]", file=sys.stderr)
        sys.exit(1)
    sys.exit(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else ""))
