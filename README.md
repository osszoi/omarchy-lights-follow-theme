# omarchy-hardware-lights-follow-theme

Makes the physical lights on the desk follow the current [Omarchy](https://omarchy.org) theme accent:

| Hardware | How |
|---|---|
| PC fans (Cooler Master ARGB controller `2516:1011`) | OpenRGB in Direct mode (SDK), the accent-shade gradient flows around each fan, each header with its own offset/direction |
| Secretlab MAGNUS Pro MAGRGB strip (Nanoleaf Smart Lighting Edition) | Nanoleaf local API, a `flow` effect with a palette of accent shades |
| Govee lights (H6061 Glide Hexa, H6056 Flow Plus) | Govee LAN API, per-segment gradient of accent shades slowly rotating |

Runs from Omarchy's `theme-set` hook, so `omarchy theme set <name>` (or the theme picker) updates everything. Fans and Govee are animated by one small user service (`omarchy-lights.service`) that re-reads the palette whenever the theme changes; the desk gets a Nanoleaf effect written once per theme change.

## Install

```bash
./install.sh            # asks for sudo once (openrgb, ufw rule), then waits for the desk's API pairing window
./install.sh --skip-pair
```

Requirements you have to do once, by hand:

- Govee Home app -> each light -> settings (gear) -> **LAN Control** on. Without it the lights never answer on the LAN.
- If `ufw` is active the installer adds one rule (inbound udp 4002 from your LAN) so the lights' discovery replies get through.
- The MAGRGB strip must be on the same Wi-Fi as this PC. To pair: Nanoleaf app -> MAGRGB -> device settings -> **Connect to API**, while `omarchy-lights pair-desk` is polling (30 s window). Never hold the controller's power button for that: 10 s is a factory reset.
- OpenRGB runs with a private config (`~/.config/omarchy-lights/openrgb`) where only the Cooler Master detector is enabled: the stock detection segfaults on exit with this GPU/monitor/mic combo, and it keeps your own OpenRGB setup untouched.

## Uninstall

```bash
./uninstall.sh          # keeps ~/.config/omarchy-lights (desk token)
./uninstall.sh --purge
```

## Usage

```bash
omarchy-lights status
omarchy-lights sync            # re-apply current theme
omarchy-lights sync '#FF5500'  # try any color
omarchy-lights palette         # see the generated shades
omarchy-lights govee scan
omarchy-lights fans info       # what openrgb sees (zones, modes)
omarchy-lights restart         # after editing config.json
omarchy-lights log
journalctl --user -u omarchy-lights -f
```

## Two (or more) colors per theme

A theme can ship a `lights.rgb` next to its `colors.toml`, one hex per line (same convention as Omarchy's `keyboard.rgb`; a leading `#` is tolerated):

```
3a8bcc
4b8537
```

The palette then flows through all of them (shades of A → blend → shades of B → blend → back). Without the file the theme's `accent` is used. Try colors by hand with `omarchy-lights sync 3a8bcc 4b8537`.

## Config

`~/.config/omarchy-lights/config.json`

```json
{
  "fans":  {"enabled": true, "mode": "gradient", "period_seconds": 12, "fps": 8,
            "min_brightness": 0.8, "max_brightness": 1.0, "gamma": 2.2,
            "zone_leds": {"0": 48, "1": 48, "2": 48, "3": 48}, "sdk_port": 6763},
  "desk":  {"enabled": true, "host": "192.168.1.37", "port": 16021, "token": "...", "effect": "flow"},
  "govee": {
    "enabled": true,
    "fps": 4,
    "period_seconds": 12,
    "segments": {"H6061": 10, "H6056": 12},
    "devices": {"<device-id>": {"segments": 8, "enabled": true}}
  }
}
```

- `fans.zone_leds`: LEDs per ARGB header (max 48). Extra LEDs beyond what is physically connected are harmless; lower it to save USB bandwidth.
- `fans.mode`: `gradient` (shades of the accent flowing around each fan, `period_seconds` per loop) or `brightness` (single accent color, every LED wandering between `min_brightness` and `max_brightness`, perceptual via `gamma`).
- `desk.effect`: `flow`, `wheel`, `fade`, `highlight` or `static`.
- `govee.segments`: segment count per SKU (check the layout page in the Govee app); per device override under `devices`.
