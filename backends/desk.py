#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
from common import load_config, load_palette, save_config  # noqa: E402

PLUGINS = {
    "flow": "027842e4-e1d6-4a4c-a731-be74a1ebd4cf",
    "wheel": "6970681a-20b5-4c5e-8813-bdaebc4ee4fa",
    "fade": "b3fd723a-aae8-4c99-bf2b-087159e0ef53",
    "highlight": "70b7c636-6bf8-491f-89c1-f4103508d642",
}


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def request(cfg, method, path, body=None, timeout=4):
    desk = cfg["desk"]
    url = f"http://{desk['host']}:{desk['port']}/api/v1/{desk['token']}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        return r.status, (json.loads(raw) if raw else None)


def find_host():
    try:
        out = subprocess.run(["avahi-browse", "-rtp", "_nanoleafapi._tcp"], capture_output=True, text=True, timeout=8).stdout
    except Exception:
        return None
    for line in out.splitlines():
        parts = line.split(";")
        if parts[0] == "=" and parts[2] == "IPv4" and len(parts) > 8:
            return parts[7], int(parts[8])
    return None


def pair(wait=150):
    cfg = load_config()
    log("in the Nanoleaf app open the MAGRGB -> device settings -> 'Connect to API' (30s window). Polling for %ds..." % wait)
    log("do NOT hold the controller's power button: 10s = factory reset")
    end = time.time() + wait
    last_discovery = 0.0
    while time.time() < end:
        if not cfg["desk"]["host"] or time.time() - last_discovery > 15:
            found = find_host()
            last_discovery = time.time()
            if found and (found[0], found[1]) != (cfg["desk"]["host"], cfg["desk"]["port"]):
                cfg["desk"]["host"], cfg["desk"]["port"] = found
                save_config(cfg)
                log("desk found at", found[0])
        if not cfg["desk"]["host"]:
            time.sleep(3)
            continue
        url = f"http://{cfg['desk']['host']}:{cfg['desk']['port']}/api/v1/new"
        try:
            with urllib.request.urlopen(urllib.request.Request(url, method="POST"), timeout=3) as r:
                cfg["desk"]["token"] = json.loads(r.read())["auth_token"]
                save_config(cfg)
                log("paired, token saved")
                return 0
        except urllib.error.HTTPError as e:
            if e.code != 403:
                log("unexpected", e.code)
        except Exception as e:
            log("desk not reachable at", cfg["desk"]["host"], "-", e)
        time.sleep(2)
    log("timed out waiting for the pairing window")
    return 1


def info():
    cfg = load_config()
    status, data = request(cfg, "GET", "")
    print(json.dumps({k: data.get(k) for k in ("name", "model", "firmwareVersion", "state", "effects", "panelLayout")}, indent=2))


def rediscover(cfg):
    found = find_host()
    if found and (found[0], found[1]) != (cfg["desk"]["host"], cfg["desk"]["port"]):
        cfg["desk"]["host"], cfg["desk"]["port"] = found
        save_config(cfg)
        log("desk moved to", found[0])
        return True
    return False


def apply():
    cfg = load_config()
    if not cfg["desk"]["token"]:
        log("desk not paired, run: omarchy-lights pair-desk")
        return 1
    palette = load_palette()
    if not palette:
        log("no palette")
        return 1
    try:
        request(cfg, "GET", "/state/on", timeout=3)
    except urllib.error.HTTPError:
        raise
    except Exception:
        if not rediscover(cfg):
            log("desk unreachable at", cfg["desk"]["host"])
            return 1
    effect = cfg["desk"].get("effect", "flow")
    if effect == "static":
        return static(cfg, palette)
    body = {
        "write": {
            "command": "display",
            "version": "2.0",
            "animType": "plugin",
            "colorType": "HSB",
            "animName": "Omarchy",
            "palette": palette["hsb"],
            "pluginType": "color",
            "pluginUuid": PLUGINS.get(effect, PLUGINS["flow"]),
            "pluginOptions": [
                {"name": "transTime", "value": 40},
                {"name": "delayTime", "value": 10},
                {"name": "linDirection", "value": "right"},
                {"name": "loop", "value": True},
            ],
        }
    }
    try:
        status, _ = request(cfg, "PUT", "/effects", body, timeout=6)
        log("desk effect", effect, "applied", palette["accent"])
        return 0
    except urllib.error.HTTPError as e:
        log("effect write failed", e.code, e.read()[:200], "- falling back to static")
        return static(cfg, palette)


def static(cfg, palette):
    hsb = palette["hsb"][1]
    body = {"on": {"value": True}, "hue": {"value": hsb["hue"]}, "sat": {"value": hsb["saturation"]}}
    request(cfg, "PUT", "/state", body)
    log("desk static", palette["accent"])
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "apply"
    try:
        if cmd == "pair":
            sys.exit(pair())
        elif cmd == "info":
            info()
        elif cmd == "apply":
            sys.exit(apply())
        else:
            print("usage: desk.py pair|info|apply", file=sys.stderr)
            sys.exit(1)
    except urllib.error.HTTPError as e:
        log("http", e.code, e.read()[:300])
        sys.exit(1)
    except Exception as e:
        log("error", e)
        sys.exit(1)
