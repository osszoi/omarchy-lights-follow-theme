#!/usr/bin/env python3
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
from common import load_config  # noqa: E402
import fans  # noqa: E402
import govee  # noqa: E402

stop = threading.Event()
THEME_NAME = Path.home() / ".local/state/omarchy/current/theme.name"
LIGHTS_BIN = Path(__file__).resolve().parent.parent / "bin" / "omarchy-lights"


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


def guarded(name, fn):
    while not stop.is_set():
        try:
            fn(stop)
        except Exception as e:
            print(time.strftime("%H:%M:%S"), f"[{name}] crashed: {e}, restarting in 10s", flush=True)
            stop.wait(10)


def main():
    cfg = load_config()
    threads = [threading.Thread(target=guarded, args=("watch", watch_theme), daemon=True)]
    if cfg["fans"].get("enabled", True):
        threads.append(threading.Thread(target=guarded, args=("fans", fans.run), daemon=True))
    if cfg["govee"].get("enabled", True):
        threads.append(threading.Thread(target=guarded, args=("govee", govee.daemon), daemon=True))
    for t in threads:
        t.start()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    while not stop.is_set():
        stop.wait(1)
    for t in threads:
        t.join(timeout=5)


if __name__ == "__main__":
    main()
