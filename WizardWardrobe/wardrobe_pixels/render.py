"""Turns a sprite recipe (Gemma's description + real colors) into pixel art."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

import numpy as np
from PIL import Image

from .palette import Hex, hex_to_rgb, luminance, ramp, snap
from .templates import SIZE, TEMPLATES

PATTERNS = ["solid", "striped", "vertical_striped", "plaid", "checkered",
            "polka_dot", "floral", "camo", "denim"]
GRAPHICS = ["none", "text", "letter", "star", "heart", "circle", "logo"]


@dataclass
class SpriteRecipe:
    subtype: str
    primary: Hex
    secondary: Hex | None = None
    accent: Hex | None = None
    pattern: str = "solid"
    graphic: str = "none"
    graphic_letter: str | None = None
    seed: str = "0"                  # e.g. item id; varies denim/camo noise per item
    snap_to_palette: bool = True
    extra: dict = field(default_factory=dict)


# ---------------------------------------------------------------- graphics --

FONT_3x5 = {
    "A": "010101111101101", "B": "110101110101110", "C": "011100100100011",
    "D": "110101101101110", "E": "111100110100111", "F": "111100110100100",
    "G": "011100101101011", "H": "101101111101101", "I": "111010010010111",
    "J": "001001001101010", "K": "101101110101101", "L": "100100100100111",
    "M": "101111111101101", "N": "110101101101101", "O": "010101101101010",
    "P": "110101110100100", "Q": "010101101110011", "R": "110101110101101",
    "S": "011100010001110", "T": "111010010010010", "U": "101101101101111",
    "V": "101101101101010", "W": "101101101111101", "X": "101101010101101",
    "Y": "101101010010010", "Z": "111001010100111", "0": "111101101101111",
    "1": "010110010010111", "2": "110001010100111", "3": "110001010001110",
    "4": "101101111001001", "5": "111100110001110", "6": "011100111101111",
    "7": "111001010010010", "8": "111101111101111", "9": "111101111001110",
}

MOTIFS = {
    "star":   ["00100", "01110", "11111", "01010", "10001"],
    "heart":  ["01010", "11111", "11111", "01110", "00100"],
    "circle": ["01110", "11111", "11111", "11111", "01110"],
    "logo":   ["111111", "100001", "111111"],
    "text":   ["1110111", "0000000", "1111011"],
}


def _glyph(recipe: SpriteRecipe) -> list[str] | None:
    g = recipe.graphic
    if g == "letter":
        ch = (recipe.graphic_letter or "").strip().upper()[:1]
        if ch in FONT_3x5:
            bits = FONT_3x5[ch]
            return [bits[i:i + 3] for i in range(0, 15, 3)]
        g = "logo"  # unknown letter -> generic logo
    return MOTIFS.get(g)


# ---------------------------------------------------------------- patterns --

def _noise(x: int, y: int, seed: str) -> float:
    h = hashlib.blake2b(f"{seed}:{x}:{y}".encode(), digest_size=2).digest()
    return int.from_bytes(h, "big") / 65535


def _pattern_color(x: int, y: int, pattern: str, p: Hex, s: Hex, rp: dict, seed: str) -> Hex:
    if pattern == "striped":
        return s if (y // 2) % 2 == 0 else p
    if pattern == "vertical_striped":
        return s if (x // 2) % 2 == 0 else p
    if pattern == "checkered":
        return s if ((x // 2) + (y // 2)) % 2 == 0 else p
    if pattern == "plaid":
        h, v = y % 6 in (0, 1), x % 6 in (0, 1)
        if h and v:
            return ramp(s, False)["shade"] if s != p else rp["shade"]
        if h or v:
            return s
        return p
    if pattern == "polka_dot":
        off = 2 if (y // 4) % 2 else 0
        return s if (y % 4 == 1 and (x + off) % 4 == 1) else p
    if pattern == "floral":
        off = 3 if (y // 5) % 2 else 0
        cx, cy = (x + off) % 6, y % 5
        if (cx, cy) == (2, 2):
            return rp["light"]
        if (cx, cy) in ((1, 2), (3, 2), (2, 1), (2, 3)):
            return s
        return p
    if pattern == "camo":
        n = _noise(x // 3, y // 3, seed)
        return s if n < 0.33 else (rp["shade"] if n < 0.55 else p)
    if pattern == "denim":
        n = _noise(x, y, seed)
        return rp["light"] if n < 0.07 else (rp["shade"] if n > 0.95 else p)
    return p


# ---------------------------------------------------------------- renderer --

def _resolve_colors(r: SpriteRecipe, category: str) -> tuple[Hex, Hex | None, Hex]:
    fix = snap if r.snap_to_palette else (lambda c: c.lower())
    primary = fix(r.primary)
    secondary = fix(r.secondary) if r.secondary else None
    if secondary == primary:
        secondary = None
    contrast = fix("#ffffff") if luminance(primary) < 60 else ramp(primary, r.snap_to_palette)["outline"]
    accent = fix(r.accent) if r.accent else (secondary or contrast)
    if accent == primary:
        accent = contrast
    return primary, secondary, accent


def render_sprite(recipe: SpriteRecipe, scale: int = 1) -> Image.Image:
    tpl = TEMPLATES[recipe.subtype]
    grid = np.array([list(row) for row in tpl.rows])
    snap_on = recipe.snap_to_palette

    primary, secondary, accent = _resolve_colors(recipe, tpl.category)
    rp = ramp(primary, snap_on)
    if secondary:
        trim = secondary
    elif tpl.category == "shoes":
        trim = snap("#f4f4f4") if snap_on else "#f4f4f4"
    else:
        trim = primary
    rt = ramp(trim, snap_on)
    pat_second = secondary or (rp["light"] if luminance(primary) < 50 else rp["shade"])
    lace = (snap("#ffffff") if snap_on else "#ffffff") if luminance(primary) < 60 else rp["shade"]

    mask = grid != "."
    pad = np.pad(mask, 2, constant_values=False)

    def at(dx: int, dy: int) -> np.ndarray:  # mask value of the neighbor at (x+dx, y+dy)
        return pad[2 + dy:2 + dy + SIZE, 2 + dx:2 + dx + SIZE]

    # Light comes from the top-left: shade the right/bottom edges, highlight top/left.
    shade_band = mask & (~at(1, 0) | ~at(2, 0) | ~at(0, 1))
    light_band = mask & (~at(-1, 0) | ~at(0, -1)) & ~shade_band
    outline = ~mask & (at(1, 0) | at(-1, 0) | at(0, 1) | at(0, -1))

    img = np.zeros((SIZE, SIZE, 4), dtype=np.uint8)

    def put(x: int, y: int, color: Hex):
        img[y, x, :3] = hex_to_rgb(color)
        img[y, x, 3] = 255

    for y in range(SIZE):
        for x in range(SIZE):
            ch = grid[y, x]
            if ch == ".":
                if outline[y, x]:
                    # Outline takes the darkest tone of whatever region it borders.
                    nbrs = [grid[y + dy, x + dx] for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                            if 0 <= x + dx < SIZE and 0 <= y + dy < SIZE]
                    put(x, y, rt["outline"] if "t" in nbrs and "#" not in nbrs else rp["outline"])
                continue
            if ch == "d":
                put(x, y, rp["outline"])
                continue
            if ch == "l":
                put(x, y, lace)
                continue
            if ch == "t":
                base, rr = trim, rt
            else:  # '#'
                base = _pattern_color(x, y, recipe.pattern, primary, pat_second, rp, recipe.seed)
                rr = ramp(base, snap_on)
            if shade_band[y, x]:
                put(x, y, rr["shade"])
            elif light_band[y, x]:
                put(x, y, rr["light"])
            else:
                put(x, y, base)

    glyph = _glyph(recipe)
    if glyph and tpl.graphic_anchor:
        cx, top = tpl.graphic_anchor
        w = len(glyph[0])
        left = cx - w // 2
        for gy, row in enumerate(glyph):
            for gx, bit in enumerate(row):
                x, y = left + gx, top + gy
                if bit == "1" and 0 <= x < SIZE and 0 <= y < SIZE and grid[y, x] == "#":
                    put(x, y, accent)

    sprite = Image.fromarray(img, "RGBA")
    if scale > 1:
        sprite = sprite.resize((SIZE * scale, SIZE * scale), Image.NEAREST)
    return sprite
