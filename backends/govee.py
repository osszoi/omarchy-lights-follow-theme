#!/usr/bin/env python3
import base64
import json
import math
import os
import socket
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
from common import PALETTE_FILE, hex_to_rgb255, load_config, load_palette, sample  # noqa: E402

MCAST = ("239.255.255.250", 4001)
REPLY_PORT = 4002
CTRL_PORT = 4003
RAZER_HEADER = [0xBB, 0x00, 0xFA, 0xB0, 0x00]
RAZER_ON = "uwABsQEK"
RAZER_OFF = "uwABsQAL"


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("239.255.255.250", 4001))
        return s.getsockname()[0]
    finally:
        s.close()


def scan(timeout=3.0):
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    rx.bind(("", REPLY_PORT))
    rx.settimeout(0.4)
    tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    ip = local_ip()
    tx.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(ip))
    tx.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    tx.bind((ip, 0))
    msg = json.dumps({"msg": {"cmd": "scan", "data": {"account_topic": "reserve"}}}).encode()
    found = {}
    end = time.time() + timeout
    for _ in range(2):
        tx.sendto(msg, MCAST)
        tx.sendto(msg, (ip.rsplit(".", 1)[0] + ".255", 4001))
        time.sleep(0.2)
    while time.time() < end:
        try:
            data, addr = rx.recvfrom(4096)
            d = json.loads(data)["msg"]["data"]
            found[d["device"]] = {"ip": d.get("ip", addr[0]), "sku": d.get("sku", "")}
        except socket.timeout:
            continue
        except Exception:
            continue
    rx.close()
    tx.close()
    return found


class Device:
    def __init__(self, dev_id, ip, sku, segments, brightness, tx):
        self.id = dev_id
        self.ip = ip
        self.sku = sku
        self.segments = segments
        self.brightness = brightness
        self.tx = tx
        self.last_enable = 0.0
        self.missed_scans = 0
        self.frames = 0

    def send(self, obj):
        self.tx.sendto(json.dumps(obj).encode(), (self.ip, CTRL_PORT))

    def razer(self, pt):
        self.send({"msg": {"cmd": "razer", "data": {"pt": pt}}})

    def enable(self, with_brightness=False):
        if with_brightness and self.brightness is not None:
            self.send({"msg": {"cmd": "brightness", "data": {"value": int(self.brightness)}}})
            time.sleep(0.1)
        self.razer(RAZER_ON)
        self.last_enable = time.time()

    def frame(self, colors):
        self.frames += 1
        packet = RAZER_HEADER + [len(colors)]
        for c in colors:
            packet.extend(c)
        chk = 0
        for b in packet:
            chk ^= b
        packet.append(chk)
        self.razer(base64.b64encode(bytes(packet)).decode())

    def color(self, rgb):
        r, g, b = rgb
        self.send({"msg": {"cmd": "colorwc", "data": {"color": {"r": r, "g": g, "b": b}, "colorTemInKelvin": 0}}})


def gradient(shades, segments, phase):
    if segments <= 1:
        return [sample(shades, phase)]
    return [sample(shades, phase + i / segments) for i in range(segments)]


def device_settings(cfg, dev_id, sku):
    own = cfg["govee"]["devices"].get(dev_id, {})
    segments = own.get("segments") or cfg["govee"]["segments"].get(sku, 1)
    brightness = own.get("brightness", cfg["govee"].get("brightness", {}).get(sku))
    return own.get("enabled", True), int(segments), brightness


def discover(cfg, tx, known):
    found = scan()
    changed = False
    for dev_id, info in found.items():
        enabled, segments, brightness = device_settings(cfg, dev_id, info["sku"])
        if not enabled:
            continue
        d = known.get(dev_id)
        if d is None:
            d = Device(dev_id, info["ip"], info["sku"], segments, brightness, tx)
            known[dev_id] = d
            d.enable(with_brightness=True)
            changed = True
            continue
        if d.ip != info["ip"]:
            log(d.sku, "moved", d.ip, "->", info["ip"])
            d.ip = info["ip"]
            d.enable(with_brightness=True)
            changed = True
        if d.missed_scans >= 2:
            log(d.sku, "answering scans again after", d.missed_scans * 20, "s, re-enabling razer")
            d.enable(with_brightness=True)
        d.missed_scans = 0
    for dev_id, d in known.items():
        if dev_id not in found:
            d.missed_scans += 1
            if d.missed_scans == 2:
                log(d.sku, "missing from scan (wifi drop?)")
    return changed


def daemon(stop=None):
    cfg = load_config()
    fps = max(1, int(cfg["govee"]["fps"]))
    period = max(2.0, float(cfg["govee"]["period_seconds"]))
    tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    devices = {}
    log("govee daemon starting")

    def discovery_loop():
        while stop is None or not stop.is_set():
            try:
                if discover(cfg, tx, devices):
                    log("devices:", {k: (v.ip, v.sku, v.segments, v.brightness) for k, v in devices.items()})
            except OSError as e:
                log("discovery error:", e)
            delay = 20 if devices else 15
            if stop is None:
                time.sleep(delay)
            elif stop.wait(delay):
                return

    threading.Thread(target=discovery_loop, daemon=True).start()

    palette = None
    palette_mtime = 0.0
    last_summary = time.time()
    while stop is None or not stop.is_set():
        now = time.time()
        try:
            mtime = PALETTE_FILE.stat().st_mtime
        except FileNotFoundError:
            mtime = 0.0
        if mtime != palette_mtime:
            palette_mtime = mtime
            palette = load_palette()
            if palette:
                log("palette:", palette["accent"], palette["shades"])
        if now - last_summary > 300 and devices:
            last_summary = now
            for d in devices.values():
                log("summary", d.sku, "frames/5min=%d missed_scans=%d" % (d.frames, d.missed_scans))
                d.frames = 0
        if not palette or not devices:
            time.sleep(1)
            continue
        shades = [hex_to_rgb255(s) for s in palette["shades"]]
        phase = (now / period) % 1.0
        for d in devices.values():
            if now - d.last_enable > 20:
                d.enable()
            d.frame(gradient(shades, d.segments, phase))
        time.sleep(1 / fps)


def oneshot(hex_color):
    tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    devices = {}
    discover(load_config(), tx, devices)
    rgb = hex_to_rgb255(hex_color)
    for d in devices.values():
        d.razer(RAZER_OFF)
        d.color(rgb)
        log("set", d.id, d.sku, d.ip, hex_color)
    if not devices:
        log("no govee devices found on LAN (is LAN Control enabled in the Govee Home app?)")
        return 1
    return 0


def release():
    tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    devices = {}
    discover(load_config(), tx, devices)
    for d in devices.values():
        d.razer(RAZER_OFF)
        log("released", d.id)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "scan"
    if cmd == "scan":
        print(json.dumps(scan(), indent=2))
    elif cmd == "daemon":
        daemon()
    elif cmd == "set":
        sys.exit(oneshot(sys.argv[2]))
    elif cmd == "release":
        release()
    else:
        print("usage: govee.py scan|daemon|set <#hex>|release", file=sys.stderr)
        sys.exit(1)
