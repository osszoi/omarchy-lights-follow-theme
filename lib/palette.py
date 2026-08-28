#!/usr/bin/env python3
import colorsys
import json
import sys


def hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def rgb_to_hex(rgb):
    return "#%02X%02X%02X" % tuple(max(0, min(255, round(c * 255))) for c in rgb)


def clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, v))


def shade(h, l, s, dh=0.0, dl=0.0, ds=0.0):
    return colorsys.hls_to_rgb((h + dh) % 1.0, clamp(l + dl, 0.08, 0.92), clamp(s + ds))


def mix(a, b, t=0.5):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def single(rgb):
    h, l, s = colorsys.rgb_to_hls(*rgb)
    if s < 0.12:
        return [shade(h, l, s, dl=-0.25), rgb, shade(h, l, s, dl=0.2), rgb]
    return [
        shade(h, l, s, dl=-0.22, ds=0.05),
        rgb,
        shade(h, l, s, dh=0.06, dl=0.02),
        shade(h, l, s, dl=0.18, ds=-0.05),
        rgb,
        shade(h, l, s, dh=-0.06, dl=-0.05),
    ]


def multi(rgbs):
    shades = []
    for i, rgb in enumerate(rgbs):
        h, l, s = colorsys.rgb_to_hls(*rgb)
        nxt = rgbs[(i + 1) % len(rgbs)]
        shades += [shade(h, l, s, dl=-0.2, ds=0.05), rgb, shade(h, l, s, dl=0.15, ds=-0.05), mix(rgb, nxt)]
    return shades


def build(colors):
    rgbs = [hex_to_rgb(c) for c in colors]
    shades = single(rgbs[0]) if len(rgbs) == 1 else multi(rgbs)
    hsb = []
    for c in shades:
        hh, ss, vv = colorsys.rgb_to_hsv(*c)
        hsb.append({"hue": round(hh * 360), "saturation": round(ss * 100), "brightness": round(vv * 100)})
    return {
        "accent": rgb_to_hex(rgbs[0]),
        "colors": [rgb_to_hex(c) for c in rgbs],
        "shades": [rgb_to_hex(c) for c in shades],
        "hsb": hsb,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: palette.py RRGGBB [RRGGBB ...]", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(build(sys.argv[1:]), indent=2))
