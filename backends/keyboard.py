#!/usr/bin/env python3
import glob
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
from common import hex_to_rgb255, load_config, load_palette, record_result  # noqa: E402
from openrgb_sdk import MODE_FLAG_MODE_SPECIFIC_COLOR, OpenRGBClient, mode_with_color  # noqa: E402
import fans  # noqa: E402


def log(*a):
    print(time.strftime("%H:%M:%S"), "[keyboard]", *a, flush=True)


def hidraw_nodes(usb_id):
    """The keyboard only speaks RGB over the cable, so look for its USB id among the hidraw devices."""
    if not usb_id or ":" not in usb_id:
        return []
    vid, pid = usb_id.lower().split(":", 1)
    want = "HID_ID=0003:%08X:%08X" % (int(vid, 16), int(pid, 16))
    nodes = []
    for uevent in glob.glob("/sys/class/hidraw/hidraw*/device/uevent"):
        try:
            if want in open(uevent).read():
                nodes.append("/dev/" + uevent.split("/")[4])
        except OSError:
            continue
    return nodes


def connected(usb_id):
    if not usb_id or ":" not in usb_id:
        return True
    return bool(hidraw_nodes(usb_id))


def enumerated_at(usb_id):
    """When the keyboard last showed up on USB: the device nodes are created on enumeration."""
    times = []
    for node in hidraw_nodes(usb_id):
        try:
            times.append(os.stat(node).st_ctime)
        except OSError:
            continue
    return max(times) if times else 0.0


def daemon_running():
    return subprocess.run(["systemctl", "--user", "is-active", "--quiet", "omarchy-lights.service"]).returncode == 0


def wait_for_server(port, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        if fans.port_open(port):
            return True
        time.sleep(0.5)
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
    # the daemon owns the server while it syncs something: never race it with a second openrgb on the same port
    if daemon_running() and fans.daemon_serves(cfg):
        if not wait_for_server(port):
            log("daemon is running but its openrgb server never came up on port", port)
            record_result("keyboard", {"ok": False, "present": True, "detail": "openrgb server not up", "at": time.time()})
            return 1
    fans.SERVER.use()
    client = None
    try:
        fans.SERVER.ensure(port)
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
        time.sleep(0.2)
        # update_mode is RAM only on this firmware; a power cycle brings back whatever was saved last
        client.save_mode(idx, mode_idx, raw)
        time.sleep(0.2)
        log(info["name"], "->", effect, palette["accent"], "(saved to keyboard)")
        record_result("keyboard", {"ok": True, "present": True, "name": info["name"],
                                   "detail": "%s · %s" % (effect, palette["accent"]), "at": time.time()})
        return 0
    finally:
        if client:
            client.close()
        fans.SERVER.release()


def info():
    cfg = load_config()
    port = int(cfg["fans"].get("sdk_port", 6763))
    fans.SERVER.use()
    fans.SERVER.ensure(port)
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
    fans.SERVER.release()


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
