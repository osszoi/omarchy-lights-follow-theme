#!/bin/bash
set -u

PALETTE="${XDG_STATE_HOME:-$HOME/.local/state}/omarchy-lights/palette.json"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/omarchy-lights"

command -v openrgb >/dev/null || { echo "openrgb not installed"; exit 0; }
[[ -f $PALETTE ]] || { echo "no palette"; exit 1; }
[[ -f $CONFIG_DIR/openrgb/OpenRGB.json ]] || { echo "no private openrgb config yet (run install.sh)"; exit 1; }

accent=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['accent'].lstrip('#'))" "$PALETTE")
mapfile -t indices < <(timeout 30 openrgb --config "$CONFIG_DIR/openrgb" --noautoconnect --list-devices 2>/dev/null | grep -E "^[0-9]+: .*COOLERMASTER ARGB" | cut -d: -f1)
(( ${#indices[@]} > 0 )) || { echo "no Cooler Master ARGB controller found"; exit 1; }

args=()
for i in "${indices[@]}"; do args+=(--device "$i" --mode static --color "$accent"); done
timeout 20 openrgb --config "$CONFIG_DIR/openrgb" --noautoconnect "${args[@]}" >/dev/null 2>&1 \
  && echo "fans static #$accent (devices ${indices[*]})" || { echo "openrgb failed (exit $?)"; exit 1; }
