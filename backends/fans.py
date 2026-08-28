#!/usr/bin/env python3
import json
import math
import os
import random
import shutil
import socket
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
from common import CONFIG_DIR, PALETTE_FILE, hex_to_rgb255, load_config, load_palette, sample  # noqa: E402
from openrgb_sdk import OpenRGBClient  # noqa: E402

OPENRGB_CONFIG = CONFIG_DIR / "openrgb"
KEEP_DETECTORS = {"Cooler Master ARGB"}


def log(*a):
    print(time.strftime("%H:%M:%S"), "[fans]", *a, flush=True)


def ensure_openrgb_config():
    OPENRGB_CONFIG.mkdir(parents=True, exist_ok=True)
    cfg_file = OPENRGB_CONFIG / "OpenRGB.json"
    if not cfg_file.exists():
        subprocess.run(["openrgb", "--config", str(OPENRGB_CONFIG), "--noautoconnect", "--nodetect", "--list-devices"],
                       capture_output=True, timeout=30)
    data = json.loads(cfg_file.read_text()) if cfg_file.exists() else {}
    detectors = data.setdefault("Detectors", {}).setdefault("detectors", {})
    if not detectors:
        global_cfg = os.path.expanduser("~/.config/OpenRGB/OpenRGB.json")
        if os.path.exists(global_cfg):
            detectors.update(json.load(open(global_cfg)).get("Detectors", {}).get("detectors", {}))
    changed = False
    for k in list(detectors):
        want = k in KEEP_DETECTORS
        if detectors[k] != want:
            detectors[k] = want
            changed = True
    if changed or not cfg_file.exists():
        cfg_file.write_text(json.dumps(data, indent=1))


def port_open(port):
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def start_server(port):
    if port_open(port):
        return None
    proc = subprocess.Popen(["openrgb", "--config", str(OPENRGB_CONFIG), "--noautoconnect", "--server", "--server-port", str(port)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        if port_open(port):
            return proc
        if proc.poll() is not None:
            raise RuntimeError(f"openrgb server exited with {proc.returncode}")
        time.sleep(0.2)
    proc.kill()
    raise RuntimeError("openrgb server did not open its port")


class Controller:
    def __init__(self, client, idx, info, zone_leds):
        self.client = client
        self.idx = idx
        self.name = info["name"]
        for zone_idx, zone in enumerate(info["zones"]):
            want = zone_leds.get(str(zone_idx))
            if want is not None and zone["leds_min"] != zone["leds_max"]:
                want = max(zone["leds_min"], min(zone["leds_max"], int(want)))
                if want != zone["leds_count"]:
                    client.resize_zone(idx, zone_idx, want)
                    time.sleep(0.1)
        info = client.controller(idx)
        direct = next((i for i, m in enumerate(info["modes"]) if m["name"] in ("Direct", "Custom")), None)
        if direct is None:
            raise RuntimeError(f"{self.name}: no direct mode")
        client.update_mode(idx, direct, info["modes"][direct]["raw"])
        time.sleep(0.1)
        self.num_leds = info["num_leds"]
        self.zones = [z["leds_count"] for z in info["zones"]]
        self.phase = [random.uniform(0, 2 * math.pi) for _ in range(self.num_leds)]
        self.period = [random.uniform(4.0, 9.0) for _ in range(self.num_leds)]
        self.positions = []
        for zone_idx, count in enumerate(self.zones):
            offset = random.random()
            direction = random.choice((1, -1))
            for j in range(count):
                self.positions.append((offset, direction, j / count if count > 1 else 0.0))

    def frame_brightness(self, accent, lo, hi, gamma, t):
        colors = []
        for i in range(self.num_leds):
            k = lo + (hi - lo) * (0.5 + 0.5 * math.sin(2 * math.pi * t / self.period[i] + self.phase[i]))
            k = k ** gamma
            colors.append(tuple(round(c * k) for c in accent))
        self.client.update_leds(self.idx, colors)

    def frame_gradient(self, shades, period, t):
        phase = t / period
        colors = [sample(shades, offset + direction * phase + frac) for offset, direction, frac in self.positions]
        self.client.update_leds(self.idx, colors)


def connect(cfg):
    fans = cfg["fans"]
    port = int(fans.get("sdk_port", 6763))
    ensure_openrgb_config()
    proc = start_server(port)
    match = fans.get("device_match", "COOLERMASTER ARGB")
    zone_leds = {str(k): v for k, v in fans.get("zone_leds", {"0": 48, "1": 48, "2": 48, "3": 48}).items()}
    controllers = []
    client = None
    for attempt in range(10):
        try:
            client = OpenRGBClient(port=port)
            for i in range(client.controller_count()):
                info = client.controller(i)
                if match.lower() in info["name"].lower():
                    controllers.append(Controller(client, i, info, zone_leds))
        except (OSError, ConnectionError, ValueError) as e:
            log("connect attempt", attempt + 1, "failed:", e)
            controllers = []
        if controllers:
            break
        if client:
            client.close()
        time.sleep(1)
        if proc is None:
            proc = start_server(port)
        client = None
    if client is None:
        client = OpenRGBClient(port=port)
    log("server protocol", client.server_protocol, "controllers:", [(c.name, c.zones) for c in controllers])
    return proc, client, controllers


def run(stop=None):
    cfg = load_config()
    fans = cfg["fans"]
    fps = max(1, int(fans.get("fps", 8)))
    lo = float(fans.get("min_brightness", 0.8))
    hi = float(fans.get("max_brightness", 1.0))
    gamma = float(fans.get("gamma", 2.2))
    mode = fans.get("mode", "gradient")
    period = max(2.0, float(fans.get("period_seconds", 12)))
    proc = client = None
    controllers = []
    accent = None
    shades = None
    mtime = 0.0
    while stop is None or not stop.is_set():
        try:
            if client is None:
                proc, client, controllers = connect(cfg)
                if not controllers:
                    log("no matching controllers, retrying in 30s")
                    client.close(); client = None
                    time.sleep(30)
                    continue
            try:
                m = PALETTE_FILE.stat().st_mtime
            except FileNotFoundError:
                m = 0.0
            if m != mtime:
                mtime = m
                p = load_palette()
                accent = hex_to_rgb255(p["accent"]) if p else None
                shades = [hex_to_rgb255(x) for x in p["shades"]] if p else None
                if p:
                    log("accent", p["accent"], "mode", mode)
            if accent is None:
                time.sleep(1)
                continue
            t = time.time()
            for c in controllers:
                if mode == "brightness":
                    c.frame_brightness(accent, lo, hi, gamma, t)
                else:
                    c.frame_gradient(shades, period, t)
            time.sleep(1 / fps)
        except Exception as e:
            log("error:", e, "- reconnecting in 5s")
            if client:
                client.close()
            client = None
            if proc and proc.poll() is None:
                proc.terminate()
            proc = None
            time.sleep(5)
    if client:
        client.close()
    if proc and proc.poll() is None:
        proc.terminate()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "info":
        cfg = load_config()
        proc, client, controllers = connect(cfg)
        for i in range(client.controller_count()):
            info = client.controller(i)
            print(i, info["name"], "active_mode", info["active_mode"], "leds", info["num_leds"])
            print("   modes:", [m["name"] for m in info["modes"]])
            print("   zones:", [(z["name"], z["leds_count"], z["leds_max"]) for z in info["zones"]])
        client.close()
        if proc:
            proc.terminate()
    else:
        run()
