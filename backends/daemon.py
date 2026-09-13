#!/usr/bin/env python3
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
from common import CONFIG_FILE, STATE_DIR, STATUS_FILE, load_config, load_palette, read_results  # noqa: E402
import fans  # noqa: E402
import govee  # noqa: E402
import keyboard  # noqa: E402

stop = threading.Event()
THEME_NAME = Path.home() / ".local/state/omarchy/current/theme.name"
LIGHTS_BIN = Path(__file__).resolve().parent.parent / "bin" / "omarchy-lights"

WORKERS = {"fans": fans.run, "govee": govee.daemon}
ONESHOTS = {"desk": ["desk.py", "apply"], "keyboard": ["keyboard.py", "apply"]}


def log(*a):
    print(time.strftime("%H:%M:%S"), "[daemon]", *a, flush=True)


def watch_theme(stop):
    last = None
    while not stop.is_set():
        try:
            st = THEME_NAME.stat()
            cur = (st.st_mtime_ns, THEME_NAME.read_text().strip())
        except FileNotFoundError:
            cur = None
        if last is not None and cur is not None and cur != last:
            print(time.strftime("%H:%M:%S"), "[watch] theme ->", cur[1], flush=True)
            subprocess.Popen([str(LIGHTS_BIN), "sync"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        last = cur
        stop.wait(0.1)


def guarded(name, fn, own_stop):
    while not own_stop.is_set():
        try:
            fn(own_stop)
            return
        except Exception as e:
            print(time.strftime("%H:%M:%S"), f"[{name}] crashed: {e}, restarting in 10s", flush=True)
            own_stop.wait(10)


def run_oneshot(name):
    script = Path(__file__).resolve().parent / ONESHOTS[name][0]
    subprocess.Popen([sys.executable, str(script)] + ONESHOTS[name][1:])


def theme_name():
    try:
        return THEME_NAME.read_text().strip()
    except OSError:
        return ""


def device_rows(cfg, running):
    results = read_results()
    rows = []
    fans_on = cfg["fans"].get("enabled", True)
    rows.append({"id": "fans", "name": "PC fans", "enabled": fans_on,
                 "present": fans.STATUS["present"],
                 "detail": fans.STATUS["detail"] if fans_on else "not syncing"})

    desk = results.get("desk", {})
    rows.append({"id": "desk", "name": "Desk strip", "enabled": cfg["desk"].get("enabled", True),
                 "present": bool(desk.get("present")),
                 "detail": desk.get("detail") or ("paired" if cfg["desk"].get("token") else "not paired")})

    kb = results.get("keyboard", {})
    plugged = keyboard.connected(cfg["keyboard"].get("usb_id", ""))
    rows.append({"id": "keyboard", "name": kb.get("name") or "Keyboard",
                 "enabled": cfg["keyboard"].get("enabled", True), "present": plugged,
                 "detail": kb.get("detail") if plugged else "USB cable disconnected"})

    devices = cfg["govee"].get("devices", {})
    seen = dict(govee.STATUS)
    for dev_id, own in devices.items():
        seen.setdefault(dev_id, {"name": "Govee light", "sku": own.get("sku", ""), "present": False,
                                 "segments": own.get("segments", 0), "ip": ""})
    govee_on = cfg["govee"].get("enabled", True)
    if not govee_on or not seen:
        rows.append({"id": "govee", "name": "Govee lights", "enabled": govee_on, "present": bool(seen),
                     "detail": "not syncing" if not govee_on
                     else ("searching the LAN" if "govee" in running else "none found on LAN")})
        return rows
    for dev_id, info in sorted(seen.items(), key=lambda kv: kv[1].get("name", "")):
        on = devices.get(dev_id, {}).get("enabled", True)
        detail = "%s · %d segments" % (info.get("sku", "?"), info.get("segments", 0))
        rows.append({"id": "govee:" + dev_id, "name": info.get("name", "Govee light"), "enabled": on,
                     "present": bool(info.get("present")),
                     "detail": detail if info.get("present") else "not answering on LAN"})
    return rows


last_status = (None, 0.0)


def write_status(cfg, running):
    global last_status
    palette = load_palette() or {}
    body = {
        "theme": theme_name(),
        "accent": palette.get("accent", ""),
        "shades": palette.get("shades", []),
        "devices": device_rows(cfg, running),
    }
    # the widget watches this file, so only rewrite on a real change plus a slow heartbeat
    same, at = last_status
    now = time.time()
    if body == same and now - at < 10:
        return
    last_status = (body, now)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATUS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(dict(body, updated=now)))
    tmp.replace(STATUS_FILE)


def main():
    threading.Thread(target=guarded, args=("watch", watch_theme, stop), daemon=True).start()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())

    running = {}
    wanted_oneshots = None
    config_mtime = None
    cfg = load_config()

    while not stop.is_set():
        try:
            m = CONFIG_FILE.stat().st_mtime
        except OSError:
            m = 0.0
        if m != config_mtime:
            config_mtime = m
            cfg = load_config()
            for name, fn in WORKERS.items():
                want = cfg[name].get("enabled", True)
                if want and name not in running:
                    log("starting", name)
                    own_stop = threading.Event()
                    t = threading.Thread(target=guarded, args=(name, fn, own_stop), daemon=True)
                    running[name] = (t, own_stop)
                    t.start()
                elif not want and name in running:
                    log("stopping", name)
                    t, own_stop = running.pop(name)
                    own_stop.set()
            oneshots = {name: cfg[name].get("enabled", True) for name in ONESHOTS}
            if wanted_oneshots is not None:
                for name, want in oneshots.items():
                    if want and not wanted_oneshots[name]:
                        log("applying", name)
                        run_oneshot(name)
            wanted_oneshots = oneshots
        write_status(cfg, running)
        stop.wait(2)

    for name, (t, own_stop) in running.items():
        own_stop.set()
    for name, (t, own_stop) in running.items():
        t.join(timeout=5)


if __name__ == "__main__":
    main()
