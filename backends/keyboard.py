#!/usr/bin/env python3
import glob
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
from common import hex_to_rgb255, load_config, load_palette, record_result  # noqa: E402
from openrgb_sdk import MODE_FLAG_MODE_SPECIFIC_COLOR, OpenRGBClient, mode_with_color  # noqa: E402
import fans  # noqa: E402


def log(*a):
    print(time.strftime("%H:%M:%S"), "[keyboard]", *a, flush=True)


def connected(usb_id):
    """The keyboard only speaks RGB over the cable, so look for its USB id."""
    if not usb_id or ":" not in usb_id:
        return True
    vid, pid = usb_id.lower().split(":", 1)
    for path in glob.glob("/sys/bus/usb/devices/*/idVendor"):
        try:
            if open(path).read().strip().lower() != vid:
                continue
            if open(os.path.join(os.path.dirname(path), "idProduct")).read().strip().lower() == pid:
                return True
        except OSError:
            continue
    return False


def find(client, match):
    for i in range(client.controller_count()):
        info = client.controller(i)
        if match.lower() in info["name"].lower():
            return i, info
    return None, None


def apply():
    cfg = load_config()
    kb = cfg["keyboard"]
    usb_id = kb.get("usb_id", "")
    match = kb.get("device_match", "Keychron")
    effect = kb.get("effect", "Solid Reactive Multinexus")

    if not connected(usb_id):
        log("not on the cable, skipping (RGB only works over USB)")
        record_result("keyboard", {"ok": False, "present": False, "detail": "USB cable disconnected", "at": time.time()})
        return 1

    palette = load_palette()
    if not palette:
        log("no palette")
        return 1
    accent = hex_to_rgb255(palette["accent"])

    changed = fans.ensure_openrgb_config()
    port = int(cfg["fans"].get("sdk_port", 6763))
    already_up = fans.port_open(port)
    if changed and already_up:
        log("openrgb detector list changed, the running server needs a restart to see the keyboard")
    proc = fans.start_server(port)
    client = None
    try:
        client = OpenRGBClient(port=port)
        idx, info = find(client, match)
        if idx is None:
            client.rescan()
            time.sleep(2)
            idx, info = find(client, match)
        if idx is None:
            log("no controller matching", repr(match), "- restart the daemon if you just enabled it")
            record_result("keyboard", {"ok": False, "present": False, "detail": "not seen by openrgb", "at": time.time()})
            return 1

        mode_idx = next((i for i, m in enumerate(info["modes"]) if m["name"].lower() == effect.lower()), None)
        if mode_idx is None:
            log("unknown effect", repr(effect), "- available:", [m["name"] for m in info["modes"]])
            record_result("keyboard", {"ok": False, "present": True, "detail": "unknown effect " + effect, "at": time.time()})
            return 1

        mode = info["modes"][mode_idx]
        raw = mode_with_color(mode, accent) if mode["flags"] & MODE_FLAG_MODE_SPECIFIC_COLOR else mode["raw"]
        client.update_mode(idx, mode_idx, raw)
        log(info["name"], "->", effect, palette["accent"])
        record_result("keyboard", {"ok": True, "present": True, "name": info["name"],
                                   "detail": "%s · %s" % (effect, palette["accent"]), "at": time.time()})
        return 0
    finally:
        if client:
            client.close()
        if proc and proc.poll() is None and not already_up:
            proc.terminate()


def info():
    cfg = load_config()
    fans.ensure_openrgb_config()
    port = int(cfg["fans"].get("sdk_port", 6763))
    proc = fans.start_server(port)
    client = OpenRGBClient(port=port)
    idx, data = find(client, cfg["keyboard"].get("device_match", "Keychron"))
    if idx is None:
        print("no keyboard controller found")
    else:
        print(data["name"], "-", data["num_leds"], "LEDs, active mode:", data["modes"][data["active_mode"]]["name"])
        print("effects:")
        for m in data["modes"]:
            tint = "themed" if m["flags"] & MODE_FLAG_MODE_SPECIFIC_COLOR else ""
            print("   %-28s %s" % (m["name"], tint))
    client.close()
    if proc:
        proc.terminate()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "apply"
    try:
        if cmd == "info":
            info()
        elif cmd == "apply":
            sys.exit(apply())
        else:
            print("usage: keyboard.py apply|info", file=sys.stderr)
            sys.exit(1)
    except Exception as e:
        log("error", e)
        sys.exit(1)
