#!/usr/bin/env python3
import colorsys
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
from common import PALETTE_FILE, hex_to_rgb255, load_config, load_palette, read_results, record_result, sample  # noqa: E402
from openrgb_sdk import OpenRGBClient  # noqa: E402
import fans  # noqa: E402
import keyboard  # noqa: E402

STATUS = {"present": False, "name": "", "detail": "not started"}


def log(*a):
    print(time.strftime("%H:%M:%S"), "[mic]", *a, flush=True)


def nap(stop, seconds):
    if stop is None:
        time.sleep(seconds)
    else:
        stop.wait(seconds)


def lift(rgb, floor):
    """LEDs off is the mic's mute light, so a dark shade must never pass for it."""
    h, s, v = colorsys.rgb_to_hsv(*(c / 255 for c in rgb))
    if v >= floor:
        return rgb
    return tuple(round(c * 255) for c in colorsys.hsv_to_rgb(h, s, floor))


class Mic:
    def __init__(self, client, idx, info):
        self.client = client
        self.idx = idx
        self.name = info["name"]
        self.num_leds = info["num_leds"]
        self.direct = next((i for i, m in enumerate(info["modes"]) if m["name"] == "Direct"), None)
        if self.direct is None:
            raise RuntimeError(f"{self.name}: no direct mode")
        self.mode_raw = info["modes"][self.direct]["raw"]
        client.update_mode(idx, self.direct, self.mode_raw)
        time.sleep(0.1)

    def show(self, colors):
        self.client.update_leds(self.idx, colors)

    def save(self, rgb):
        # the mic stores whatever the LEDs show right now, and plays it whenever nothing streams to it
        self.show([rgb] * self.num_leds)
        time.sleep(0.3)
        self.client.save_mode(self.idx, self.direct, self.mode_raw)
        time.sleep(0.5)

    def still_there(self):
        return self.client.controller(self.idx)["name"] == self.name


def connect(cfg):
    port = int(cfg["fans"].get("sdk_port", 6763))
    fans.SERVER.ensure(port)
    client = OpenRGBClient(port=port)
    # the server opens its port before detection is done
    for _ in range(10):
        idx, info = keyboard.find(client, cfg["mic"].get("device_match", "Quadcast"))
        if idx is not None:
            return client, Mic(client, idx, info)
        time.sleep(1)
    return client, None


def run(stop=None):
    cfg = load_config()
    mic = cfg["mic"]
    fps = max(1, int(mic.get("fps", 4)))
    period = max(2.0, float(mic.get("period_seconds", 12)))
    floor = float(mic.get("min_brightness", 0.35))
    usb_id = mic.get("usb_id", "")
    client = dev = shades = None
    saved = ""
    mtime = found_at = checked_at = 0.0
    fans.SERVER.use()
    while stop is None or not stop.is_set():
        try:
            if client is None:
                client, dev = connect(cfg)
                if dev is None:
                    client.close()
                    client = None
                    plugged = keyboard.connected(usb_id)
                    # openrgb only detects on start, so a mic that showed up later needs a fresh server
                    if plugged and keyboard.enumerated_at(usb_id) > fans.SERVER.started_at > 0:
                        log("mic showed up after openrgb started, restarting the server")
                        fans.SERVER.stop()
                        continue
                    STATUS.update(present=False, detail="not seen by openrgb" if plugged else "USB disconnected")
                    log(STATUS["detail"], "- retrying in 30s")
                    nap(stop, 30)
                    continue
                found_at = checked_at = time.time()
                mtime = 0.0
                log("streaming to", dev.name, "(%d LEDs)" % dev.num_leds)
            try:
                m = PALETTE_FILE.stat().st_mtime
            except FileNotFoundError:
                m = 0.0
            if m != mtime:
                mtime = m
                p = load_palette()
                if p:
                    shades = [lift(hex_to_rgb255(x), floor) for x in p["shades"]]
                    static = p.get("static", p["accent"])
                    saved = read_results().get("mic", {}).get("saved", "")
                    if saved != static:
                        dev.save(lift(hex_to_rgb255(static), floor))
                        record_result("mic", {"saved": static, "at": time.time()})
                        saved = static
                        log("saved", static, "into the mic")
            if shades is None:
                nap(stop, 1)
                continue
            now = time.time()
            if now - checked_at > 10:
                checked_at = now
                if keyboard.enumerated_at(usb_id) > found_at:
                    fans.SERVER.stop()
                    raise RuntimeError("mic re-enumerated on USB, restarted openrgb")
                if not dev.still_there():
                    raise RuntimeError("openrgb device list changed")
            phase = now / period
            dev.show([sample(shades, phase + i / len(shades)) for i in range(dev.num_leds)])
            STATUS.update(present=True, name=dev.name, detail="flowing · rests on %s" % saved if saved else "flowing")
            nap(stop, 1 / fps)
        except Exception as e:
            log("error:", e, "- reconnecting in 5s")
            STATUS.update(present=False, detail="reconnecting")
            if client:
                client.close()
            client = dev = None
            nap(stop, 5)
    if client:
        client.close()
    fans.SERVER.release()
    STATUS.update(present=False, detail="stopped")
