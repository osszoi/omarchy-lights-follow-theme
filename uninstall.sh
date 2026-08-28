#!/bin/bash
set -uo pipefail

BIN="$HOME/.local/bin/omarchy-lights"
HOOK="$HOME/.config/omarchy/hooks/theme-set.d/omarchy-lights"
UNIT_DIR="$HOME/.config/systemd/user"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/omarchy-lights"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/omarchy-lights"

step() { printf '\n\033[1;35m==>\033[0m %s\n' "$*"; }

step "releasing govee lights from streaming mode"
[[ -x $BIN ]] && "$BIN" govee release 2>/dev/null || true

step "stopping animation service"
for unit in omarchy-lights.service omarchy-lights-govee.service; do
  systemctl --user disable --now "$unit" 2>/dev/null || true
  rm -f "$UNIT_DIR/$unit"
done
systemctl --user daemon-reload
pkill -f "openrgb --config $CONFIG_DIR/openrgb" 2>/dev/null || true

step "removing hook and launcher"
rm -f "$HOOK" "$BIN"

if systemctl is-active --quiet ufw && sudo ufw status | grep -q "omarchy-lights govee"; then
  step "removing ufw rule (sudo)"
  rule=$(sudo ufw status numbered | grep "omarchy-lights govee" | head -1 | sed -E 's/^\[\s*([0-9]+)\].*/\1/')
  [[ -n $rule ]] && yes | sudo ufw delete "$rule" >/dev/null && echo "rule $rule removed"
fi

if [[ ${1:-} == --purge ]]; then
  step "removing config and state"
  rm -rf "$CONFIG_DIR" "$STATE_DIR"
else
  echo
  echo "kept $CONFIG_DIR (desk token, fan/govee settings). Use --purge to remove it too."
fi

echo
echo "openrgb was left installed; remove with: sudo pacman -Rns openrgb"
