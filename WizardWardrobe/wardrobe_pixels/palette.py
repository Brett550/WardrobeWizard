"""Color utilities: palette snapping and pixel-art shading ramps.

Every sprite color is snapped to one shared palette, so a wardrobe full of
very different photos still looks like it belongs in the same game.
"""
from __future__ import annotations

import colorsys
from functools import lru_cache

import numpy as np

# ENDESGA 32 (a popular pixel-art palette built from hue-shifted ramps).
# Swap this list out to re-theme every sprite at once.
ENDESGA_32 = [
    "#be4a2f", "#d77643", "#ead4aa", "#e4a672", "#b86f50", "#733e39", "#3e2731", "#a22633",
    "#e43b44", "#f77622", "#feae34", "#fee761", "#63c74d", "#3e8948", "#265c42", "#193c3e",
    "#124e89", "#0099db", "#2ce8f5", "#ffffff", "#c0cbdc", "#8b9bb4", "#5a6988", "#3a4466",
    "#262b44", "#181425", "#ff0044", "#68386c", "#b55088", "#f6757a", "#e8b796", "#c28569",
]

# Clothes are full of neutrals and earth tones that game palettes lack,
# so we add olive, khaki and true-grey ramps.
WARDROBE_EXTRAS = [
    "#2f3820", "#4b5a2a", "#6f7d3c", "#9aa25a",          # olive / army green
    "#b9a77c", "#d9c9a3", "#8c7a5b",                    # khaki / tan
    "#1e1e1e", "#3a3a3a", "#5e5e5e", "#8a8a8a", "#b4b4b4", "#dcdcdc",  # neutral greys
    "#2b3f63", "#4a6a9c", "#1f2a52",                    # denim / navy
    "#5b2333", "#7a2e3a",                               # maroon / burgundy
]

Hex = str
RGB = tuple[int, int, int]


def hex_to_rgb(h: Hex) -> RGB:
    h = h.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        raise ValueError(f"bad hex color: {h!r}")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def rgb_to_hex(rgb) -> Hex:
    r, g, b = (int(max(0, min(255, round(c)))) for c in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def rgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """sRGB (0-255, shape [..., 3]) -> CIE Lab (D65). Vectorized."""
    c = np.asarray(rgb, dtype=np.float64) / 255.0
    c = np.where(c > 0.04045, ((c + 0.055) / 1.055) ** 2.4, c / 12.92)
    m = np.array([[0.4124, 0.3576, 0.1805],
                  [0.2126, 0.7152, 0.0722],
                  [0.0193, 0.1192, 0.9505]])
    xyz = c @ m.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    L = 116 * f[..., 1] - 16
    a = 500 * (f[..., 0] - f[..., 1])
    b = 200 * (f[..., 1] - f[..., 2])
    return np.stack([L, a, b], axis=-1)


def lab_distance(lab1: np.ndarray, lab2: np.ndarray, l_weight: float = 1.0) -> np.ndarray:
    d = lab1 - lab2
    return np.sqrt((d[..., 0] * l_weight) ** 2 + d[..., 1] ** 2 + d[..., 2] ** 2)


class Palette:
    def __init__(self, colors: list[Hex]):
        self.colors = [c.lower() for c in colors]
        self.rgb = np.array([hex_to_rgb(c) for c in self.colors], dtype=np.float64)
        self.lab = rgb_to_lab(self.rgb)

    def nearest(self, color: Hex, *, darker_than: Hex | None = None,
                lighter_than: Hex | None = None, exclude: tuple[Hex, ...] = ()) -> Hex:
        """Nearest palette color, optionally constrained to be darker/lighter
        than a reference (used so a shadow never snaps back onto its base)."""
        target = rgb_to_lab(np.array(hex_to_rgb(color), dtype=np.float64))
        order = np.argsort(lab_distance(self.lab, target))
        for i in order:
            cand = self.colors[i]
            if cand in exclude:
                continue
            L = self.lab[i, 0]
            if darker_than is not None and L >= _lightness(darker_than) - 3:
                continue
            if lighter_than is not None and L <= _lightness(lighter_than) + 3:
                continue
            return cand
        return self.colors[order[0]]  # constraints impossible: fall back


def _lightness(h: Hex) -> float:
    return float(rgb_to_lab(np.array(hex_to_rgb(h), dtype=np.float64))[0])


def _hsv_shift(h: Hex, dh: float, ds: float, dv: float) -> Hex:
    r, g, b = (c / 255 for c in hex_to_rgb(h))
    hh, s, v = colorsys.rgb_to_hsv(r, g, b)
    hh = (hh + dh) % 1.0
    s = max(0.0, min(1.0, s + ds))
    v = max(0.0, min(1.0, v * dv))
    return rgb_to_hex(tuple(c * 255 for c in colorsys.hsv_to_rgb(hh, s, v)))


DEFAULT_PALETTE = Palette(ENDESGA_32 + WARDROBE_EXTRAS)


@lru_cache(maxsize=512)
def ramp(base: Hex, snap: bool = True) -> dict[str, Hex]:
    """Build a 4-step pixel-art ramp from one base color.

    Shadows shift hue slightly cooler and get more saturated; highlights shift
    warmer and desaturate. That hue shifting is what makes it read as
    "pixel art" instead of "a photo with the brightness turned down".
    """
    base = base.lower()
    shade = _hsv_shift(base, +0.025, +0.10, 0.70)
    light = _hsv_shift(base, -0.02, -0.08, 1.18)
    outline = _hsv_shift(base, +0.04, +0.15, 0.38)
    if base in ("#ffffff",) or _lightness(base) > 92:
        light = base  # can't go lighter than white

    if not snap:
        return {"base": base, "shade": shade, "light": light, "outline": outline}

    p = DEFAULT_PALETTE
    b = p.nearest(base)
    s = p.nearest(shade, darker_than=b)
    l = p.nearest(light, lighter_than=b) if light != base else b
    o = p.nearest(outline, darker_than=s)
    return {"base": b, "shade": s, "light": l, "outline": o}


def snap(color: Hex) -> Hex:
    return DEFAULT_PALETTE.nearest(color)


def luminance(color: Hex) -> float:
    return _lightness(color)
