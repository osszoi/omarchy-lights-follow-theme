#!/bin/bash
set -euo pipefail

ROOT=$(cd "$(dirname "$(readlink -f "$0")")" && pwd)
BIN_DIR="$HOME/.local/bin"
LIGHTS_BIN="$BIN_DIR/omarchy-lights"
HOOK_DIR="$HOME/.config/omarchy/hooks/theme-set.d"
UNIT_DIR="$HOME/.config/systemd/user"
SERVICE=omarchy-lights.service
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/omarchy-lights"
SKIP_PAIR=0
[[ ${1:-} == --skip-pair ]] && SKIP_PAIR=1

step() { printf '\n\033[1;35m==>\033[0m %s\n' "$*"; }

step "checking dependencies"
command -v python3 >/dev/null || { echo "python3 is required"; exit 1; }
command -v openrgb >/dev/null || { echo "openrgb missing, installing (sudo)"; omarchy pkg add openrgb; }
command -v avahi-browse >/dev/null || { echo "avahi-browse missing (desk discovery), installing (sudo)"; omarchy pkg add avahi; }

step "linking $LIGHTS_BIN"
mkdir -p "$BIN_DIR"
ln -sfn "$ROOT/bin/omarchy-lights" "$LIGHTS_BIN"

step "writing config + private openrgb config (only the Cooler Master detector enabled)"
mkdir -p "$CONFIG_DIR"
python3 - <<PY
import sys; sys.path.insert(0, "$ROOT/lib"); sys.path.insert(0, "$ROOT/backends")
from common import CONFIG_FILE, load_config, save_config
save_config(load_config())
import fans; fans.ensure_openrgb_config()
print(CONFIG_FILE)
PY

if systemctl is-active --quiet ufw; then
  step "ufw is active: allowing Govee LAN replies (udp 4002) from the local network (sudo)"
  iface=$(ip -4 route show default | awk '{print $5; exit}')
  subnet=$(ip -4 -o addr show dev "$iface" | awk '{print $4}' | head -1 | python3 -c "import ipaddress,sys;print(ipaddress.ip_interface(sys.stdin.read().strip()).network)")
  sudo ufw allow in on "$iface" proto udp from "$subnet" to any port 4002 comment 'omarchy-lights govee' >/dev/null && echo "rule added ($iface, $subnet)"
fi

if [[ $SKIP_PAIR == 0 ]]; then
  step "pairing desk (Secretlab MAGRGB via Nanoleaf API)"
  if python3 -c "import sys;sys.path.insert(0,'$ROOT/lib');from common import load_config;sys.exit(0 if load_config()['desk']['token'] else 1)"; then
    echo "already paired"
  else
    python3 "$ROOT/backends/desk.py" pair || echo "skipping desk for now, run 'omarchy-lights pair-desk' later"
  fi
fi

step "installing theme-set hook"
mkdir -p "$HOOK_DIR"
sed "s|__LIGHTS_BIN__|$LIGHTS_BIN|" "$ROOT/hooks/omarchy-lights" >"$HOOK_DIR/omarchy-lights"
chmod +x "$HOOK_DIR/omarchy-lights"

step "installing the bar widget"
if command -v omarchy-shell >/dev/null; then
  PLUGIN_ID=$(python3 -c "import json;print(json.load(open('$ROOT/shell-plugin/manifest.json'))['id'])")
  mkdir -p "$HOME/.config/omarchy/plugins"
  ln -sfn "$ROOT/shell-plugin" "$HOME/.config/omarchy/plugins/$PLUGIN_ID"
  omarchy-shell shell rescanPlugins >/dev/null
  sleep 0.5
  omarchy plugin enable "$PLUGIN_ID" --section right || echo "enable it by hand: omarchy plugin enable $PLUGIN_ID"
else
  echo "omarchy-shell not found, skipping the bar widget"
fi

step "installing animation service"
mkdir -p "$UNIT_DIR"
systemctl --user disable --now omarchy-lights-govee.service 2>/dev/null || true
rm -f "$UNIT_DIR/omarchy-lights-govee.service"
sed "s|__LIGHTS_BIN__|$LIGHTS_BIN|" "$ROOT/systemd/$SERVICE" >"$UNIT_DIR/$SERVICE"
systemctl --user daemon-reload
systemctl --user enable "$SERVICE" >/dev/null
systemctl --user restart "$SERVICE"

step "applying current theme"
"$LIGHTS_BIN" sync
sleep 3
"$LIGHTS_BIN" status
