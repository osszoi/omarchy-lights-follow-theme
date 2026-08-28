import json
import os
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "omarchy-lights"
STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "omarchy-lights"
CONFIG_FILE = CONFIG_DIR / "config.json"
PALETTE_FILE = STATE_DIR / "palette.json"

DEFAULT_CONFIG = {
    "fans": {
        "enabled": True,
        "fps": 8,
        "min_brightness": 0.8,
        "max_brightness": 1.0,
        "gamma": 2.2,
        "mode": "gradient",
        "period_seconds": 12,
        "zone_leds": {"0": 48, "1": 48, "2": 48, "3": 48},
        "sdk_port": 6763,
        "device_match": "COOLERMASTER ARGB",
    },
    "desk": {"enabled": True, "host": "", "port": 16021, "token": "", "effect": "flow"},
    "govee": {
        "enabled": True,
        "fps": 4,
        "period_seconds": 12,
        "segments": {"H6061": 10, "H6056": 12},
        "brightness": {"H6061": 10, "H6056": 100},
        "devices": {},
    },
}


def load_config():
    if CONFIG_FILE.exists():
        cfg = json.loads(CONFIG_FILE.read_text())
    else:
        cfg = {}
    merged = json.loads(json.dumps(DEFAULT_CONFIG))
    for k, v in cfg.items():
        if isinstance(v, dict) and isinstance(merged.get(k), dict):
            merged[k].update(v)
        else:
            merged[k] = v
    return merged


def save_config(cfg):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2) + "\n")


def load_palette():
    if not PALETTE_FILE.exists():
        return None
    return json.loads(PALETTE_FILE.read_text())


def hex_to_rgb255(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def sample(shades, pos):
    n = len(shades)
    x = (pos % 1.0) * n
    i = int(x)
    return lerp(shades[i % n], shades[(i + 1) % n], x - i)
