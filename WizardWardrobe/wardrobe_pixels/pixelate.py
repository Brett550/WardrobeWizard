"""Photo-derived pixel art: the cutout itself becomes the sprite (no templates).

  cutout -> normalize_and_center -> render_combined | render_hybrid | pixelate_and_quantize -> export_sprite

mode "shaped" (default): the combined analysis poured into the 32x32 template shapes.
mode "combined": photo silhouette + color regions, drawn like the template sprites
  (chunky, outlined, flat fills, Gemma's pattern and graphic glyph placed on the real print).
mode "hybrid": photo-detailed 96px-style render colored by Gemma's color roles.
mode "photo": plain median-cut quantization, needs no model.

Deterministic: same cutout + same PixelArtOptions -> same pixels. Runs after
segment.py, so the background never reaches the palette.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
from PIL import Image


@dataclass(frozen=True)
class PixelArtOptions:
    mode: str = "shaped"          # "shaped" | "combined" | "hybrid" | "photo"
    sprite_size: int = 40         # combined reads best at 32-48; hybrid needs ~96 for lettering
    preview_size: int = 320       # keep an integer multiple of sprite_size
    palette_colors: int = 16
    padding_fraction: float = 0.10
    dither: str = "none"          # "none" | "ordered"
    alpha_threshold: int = 128
    outline: bool = False
    min_speck: int = 3            # opaque/transparent islands smaller than this are removed
    snap_to_palette: bool = False  # hybrid only: snap ramps to the shared game palette

    def to_dict(self) -> dict:
        return asdict(self)


_BAYER4 = (np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]) + 0.5) / 16 - 0.5


def normalize_and_center(cutout: Image.Image, opts: PixelArtOptions) -> Image.Image:
    """Crop to the garment and center it on a transparent square with proportional padding."""
    rgba = cutout.convert("RGBA")
    alpha = np.asarray(rgba)[..., 3]
    bbox = Image.fromarray(((alpha >= opts.alpha_threshold) * 255).astype(np.uint8)).getbbox()
    if not bbox:
        raise ValueError("cutout has no opaque pixels")
    rgba = rgba.crop(bbox)
    w, h = rgba.size
    side = int(round(max(w, h) / (1 - 2 * opts.padding_fraction)))
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(rgba, ((side - w) // 2, (side - h) // 2))
    return canvas


def _clean_alpha(mask: np.ndarray, min_speck: int) -> np.ndarray:
    try:
        from scipy import ndimage
    except ImportError:
        return mask
    # Drop tiny opaque islands and fill tiny pinholes; 8-connectivity keeps thin
    # diagonal features (drawstrings, straps) attached.
    eight = np.ones((3, 3), bool)
    for target in (True, False):
        labels, n = ndimage.label(mask == target, structure=eight)
        if n:
            sizes = ndimage.sum(np.ones_like(mask), labels, range(1, n + 1))
            small = np.isin(labels, np.flatnonzero(sizes < min_speck) + 1)
            mask = np.where(small, not target, mask)
    return mask


def pixelate_and_quantize(square: Image.Image, opts: PixelArtOptions) -> tuple[Image.Image, list[str]]:
    """Downsample to sprite_size, harden alpha, quantize opaque pixels only. Returns (sprite, palette hexes)."""
    n = opts.sprite_size
    # Pillow resizes RGBA in premultiplied space, so edges don't pick up dark fringes.
    small = np.asarray(square.resize((n, n), Image.LANCZOS)).astype(np.float64)
    mask = _clean_alpha(small[..., 3] >= opts.alpha_threshold, opts.min_speck)
    rgb = np.clip(small[..., :3], 0, 255)

    if opts.dither == "ordered":
        rgb = np.clip(rgb + np.tile(_BAYER4, (n // 4 + 1, n // 4 + 1))[:n, :n, None] * 24, 0, 255)

    opaque = rgb[mask].astype(np.uint8)
    strip = Image.fromarray(opaque.reshape(1, -1, 3), "RGB")
    q = strip.quantize(colors=opts.palette_colors, method=Image.Quantize.MEDIANCUT,
                       dither=Image.Dither.NONE)
    pal = np.array(q.getpalette()[: 3 * opts.palette_colors], dtype=np.uint8).reshape(-1, 3)
    idx = np.asarray(q)[0]

    out = np.zeros((n, n, 4), np.uint8)
    out[mask, :3] = pal[idx]
    out[mask, 3] = 255

    if opts.outline:
        try:
            from scipy import ndimage
            ring = ndimage.binary_dilation(mask) & ~mask
            used = pal[np.unique(idx)]
            dark = used[np.argmin(used.astype(int).sum(1))] // 2
            out[ring, :3] = dark
            out[ring, 3] = 255
        except ImportError:
            pass

    used = np.unique(out[out[..., 3] > 0][:, :3], axis=0)
    palette = ["#%02x%02x%02x" % tuple(int(c) for c in rgb_) for rgb_ in used]
    return Image.fromarray(out, "RGBA"), palette


def export_sprite(sprite: Image.Image, opts: PixelArtOptions) -> tuple[Image.Image, Image.Image]:
    """(master sprite, nearest-neighbor preview). Never bilinear/bicubic here."""
    if opts.preview_size % opts.sprite_size:
        raise ValueError("preview_size must be an integer multiple of sprite_size (uneven pixels otherwise)")
    return sprite, sprite.resize((opts.preview_size, opts.preview_size), Image.NEAREST)


# ------------------------------------------------------------------ hybrid --
# Photo decides WHERE pixels go; Gemma decides WHAT the colors mean.
#   1. Every hi-res pixel is assigned to one anchor color (Gemma's primary /
#      secondary / accent, plus clearly distinct measured detail colors).
#   2. Each sprite pixel is a weighted majority vote over its block. Graphic and
#      trim anchors vote heavier, so thin prints/cuffs survive the downsample
#      instead of blending into the fabric.
#   3. The winner is drawn with that anchor's pixel-art ramp (shade/base/light),
#      picked by how much lighter/darker the photo was there.

ROLE_WEIGHTS = {"primary": 1.0, "secondary": 1.6, "accent": 2.6, "detail": 2.0}
DETAIL_MIN_DISTANCE = 25.0   # Lab distance an unchosen measured color needs to count as its own detail
WORK_FACTOR = 6              # hi-res classification pixels per sprite pixel (per side)


@dataclass(frozen=True)
class Anchor:
    hex: str
    role: str                 # primary | secondary | accent | detail


def anchors_from_spec(recipe_colors: dict, measured: list[dict]) -> list[Anchor]:
    """Gemma's chosen colors first, then measured colors far from all of them (e.g. a white
    outline around a print). Measured colors near a chosen one are assumed to be its shading."""
    from .palette import hex_to_rgb, lab_distance, rgb_to_lab

    anchors = [Anchor(recipe_colors[r].lower(), r) for r in ("primary", "secondary", "accent")
               if recipe_colors.get(r)]
    anchors = [a for i, a in enumerate(anchors) if a.hex not in {b.hex for b in anchors[:i]}]
    seen = {a.hex for a in anchors}
    for c in measured:
        h = c["hex"].lower()
        if h in seen:
            continue
        lab = rgb_to_lab(np.array(hex_to_rgb(h), float))
        if all(lab_distance(lab, rgb_to_lab(np.array(hex_to_rgb(a.hex), float))) > DETAIL_MIN_DISTANCE
               for a in anchors):
            anchors.append(Anchor(h, "detail"))
            seen.add(h)
    return anchors


@dataclass
class _Classified:
    mask: np.ndarray          # (n, n) sprite silhouette
    win: np.ndarray           # (n, n) winning anchor index per sprite pixel
    d_l: np.ndarray           # (n, n) photo lightness minus the winner's anchor lightness
    a_lab: np.ndarray         # (A, 3) anchor colors in Lab
    hi_label: np.ndarray      # (n*k, n*k) nearest anchor per hi-res pixel
    hi_voters: np.ndarray     # (n*k, n*k) opaque, non-rim hi-res pixels
    hi_rgb: np.ndarray        # (n*k, n*k, 3) photo colors
    hi_fabric_dist: np.ndarray  # (n*k, n*k) Lab distance to the primary fabric (lightness down-weighted)


def _classify(square: Image.Image, anchors: list[Anchor], opts: PixelArtOptions) -> _Classified:
    from .palette import hex_to_rgb, lab_distance, rgb_to_lab

    if not anchors:
        raise ValueError("needs at least one anchor color")
    n, k = opts.sprite_size, WORK_FACTOR
    hi = np.asarray(square.resize((n * k, n * k), Image.LANCZOS)).astype(np.float64)
    opaque = hi[..., 3] >= opts.alpha_threshold
    lab = rgb_to_lab(hi[..., :3])

    a_lab = rgb_to_lab(np.array([hex_to_rgb(a.hex) for a in anchors], float))
    # Low lightness weight: a shadowed fold is still the same fabric.
    dist = np.stack([lab_distance(lab, a_lab[i], l_weight=0.35) for i in range(len(anchors))], -1)
    label = dist.argmin(-1)

    def blocks(x):  # (n*k, n*k) -> per-sprite-pixel sums
        return x.reshape(n, k, n, k).sum((1, 3))

    mask = _clean_alpha(blocks(opaque) >= (k * k) / 2, opts.min_speck)
    # Edge pixels are blended with the old background; let them shape the silhouette but not
    # vote on color, or a boosted light accent turns the whole rim speckled.
    voters = opaque
    try:
        from scipy import ndimage
        voters = ndimage.binary_erosion(opaque, iterations=2)
    except ImportError:
        pass
    votes = np.stack([blocks(voters & (label == i)) * ROLE_WEIGHTS.get(a.role, 1.0)
                      for i, a in enumerate(anchors)], -1)
    win = votes.argmax(-1)

    # Mean lightness of the winning anchor's own pixels in each block.
    l_sum = np.zeros((n, n)); l_cnt = np.zeros((n, n))
    for i in range(len(anchors)):
        sel = voters & (label == i)
        w = win == i
        l_sum[w] = blocks(np.where(sel, lab[..., 0], 0))[w]
        l_cnt[w] = blocks(sel)[w]
    # Blocks with no voters (thin rims) fall back to the primary anchor's base tone.
    d_l = np.where(l_cnt > 0, l_sum / np.maximum(l_cnt, 1) - a_lab[win, 0], 0.0)
    return _Classified(mask, win, d_l, a_lab, label, voters, hi[..., :3], dist[..., 0])


def _fold_threshold(anchor_l: float) -> float:
    # Dark fabric has a compressed lightness range, so its fold thresholds shrink with it.
    return 6.0 * float(np.clip(anchor_l / 50.0, 0.35, 1.0))


def _palette_of(out: np.ndarray) -> list[str]:
    used = np.unique(out[out[..., 3] > 0][:, :3], axis=0)
    return ["#%02x%02x%02x" % tuple(int(c) for c in u) for u in used]


def render_hybrid(square: Image.Image, anchors: list[Anchor],
                  opts: PixelArtOptions) -> tuple[Image.Image, list[str]]:
    from .palette import hex_to_rgb, ramp

    c = _classify(square, anchors, opts)
    n = opts.sprite_size
    ramps = [ramp(a.hex, opts.snap_to_palette) for a in anchors]
    out = np.zeros((n, n, 4), np.uint8)
    for i, rp in enumerate(ramps):
        t = _fold_threshold(c.a_lab[i, 0])
        for tone, sel in (("base", np.abs(c.d_l) <= t), ("shade", (c.d_l < -t) & (c.d_l >= -3.7 * t)),
                          ("outline", c.d_l < -3.7 * t), ("light", c.d_l > t)):
            out[c.mask & (c.win == i) & sel, :3] = hex_to_rgb(rp[tone])
    out[c.mask, 3] = 255

    if opts.outline:
        try:
            from scipy import ndimage
            ring = ndimage.binary_dilation(c.mask) & ~c.mask
            out[ring, :3] = hex_to_rgb(ramps[0]["outline"])
            out[ring, 3] = 255
        except ImportError:
            pass
    return Image.fromarray(out, "RGBA"), _palette_of(out)


# ---------------------------------------------------------------- combined --
# The pipeline default. Photo: silhouette, where each color region sits (hood lining,
# cuffs) and where big graphics are. Template renderer: chunky resolution, 1px outline,
# flat fills with top-left light, Gemma's pattern. Gemma: what lettering a graphic says.

DARK_L = 25.0                # below this Lab lightness, black-ish fabric gets a visible ramp


def _sprite_ramp(hex_: str, snap: bool) -> dict:
    """palette.ramp, but near-black fabric gets real highlights (x1.18 brightness of black is black)."""
    from .palette import _lightness, hex_to_rgb, ramp, rgb_to_hex

    rp = dict(ramp(hex_, snap))
    if _lightness(rp["base"]) < DARK_L:
        base = np.array(hex_to_rgb(rp["base"]), float)
        rp["light"] = rgb_to_hex(base + (np.array([92, 92, 98]) - base) * 0.45)
        rp["shade"] = rgb_to_hex(base + (np.array([60, 60, 66]) - base) * 0.18)
        rp["outline"] = rgb_to_hex(base * 0.45)
    return rp


def _tidy_regions(win: np.ndarray, mask: np.ndarray, keep: np.ndarray) -> np.ndarray:
    """One 3x3 majority pass so regions are flat blobs, not photo noise. `keep` pixels never change."""
    n = win.shape[0]
    a = int(win.max()) + 1
    pad = np.pad(np.where(mask, win, -1), 1, constant_values=-1)
    counts = np.zeros((a, n, n), int)
    for dy in range(3):
        for dx in range(3):
            nb = pad[dy:dy + n, dx:dx + n]
            for i in range(a):
                counts[i] += nb == i
    best = counts.argmax(0)
    switch = mask & ~keep & (counts.max(0) >= 5) & (best != win)
    return np.where(switch, best, win)


PRINT_BAND = (0.18, 0.82)    # a graphic's center sits inside this fraction of the garment's height/width
PRINT_COVERAGE = 0.25        # a sprite pixel is graphic if this much of its block is graphic
GRAPHIC_DISTANCE = 22.0      # Lab distance from the fabric color that counts as "not fabric"
BIG_GRAPHIC_SPAN = 0.20      # big = at least this fraction of the garment's width or height...
BIG_GRAPHIC_AREA = 0.01      # ...and at least this fraction of its area. Anything smaller is dropped.
GRAPHIC_COLORS = 4           # a big non-text graphic keeps up to this many of its own colors


@dataclass
class Graphic:
    hi: np.ndarray            # (n*k, n*k) hi-res pixels of the graphic
    center: tuple[float, float]   # sprite coords
    height: float             # sprite pixels
    width: float


def find_big_graphics(c: _Classified, n: int, pattern: str = "solid") -> list[Graphic]:
    """Big printed graphics, found on the photo itself (not from Gemma's colors), largest first.

    A graphic is a group of clearly-not-fabric pixels that sits in the middle of the garment,
    doesn't run off its edge (that's a panel, hem or undershirt), and is big enough to read at
    sprite size. Patterned fabric is skipped: its pattern would look like one big graphic."""
    try:
        from scipy import ndimage
    except ImportError:
        return []
    if pattern != "solid" or not c.mask.any():
        return []
    k = WORK_FACTOR
    sel = ndimage.binary_opening(c.hi_voters & (c.hi_fabric_dist > GRAPHIC_DISTANCE), iterations=1)
    if not sel.any():
        return []
    interior = ndimage.binary_erosion(c.hi_voters, iterations=k)
    ys, xs = np.nonzero(c.mask)
    y0, y1, x0, x1 = ys.min() * k, (ys.max() + 1) * k, xs.min() * k, (xs.max() + 1) * k
    gh, gw, area = y1 - y0, x1 - x0, c.hi_voters.sum()
    groups, count = ndimage.label(ndimage.binary_dilation(sel, iterations=k // 2))  # letters -> one word
    found = []
    for g in range(1, count + 1):
        comp = sel & (groups == g)
        size = int(comp.sum())
        if size < BIG_GRAPHIC_AREA * area or (comp & ~interior).sum() > 0.1 * size:
            continue
        py, px = np.nonzero(comp)
        h, w = py.max() - py.min() + 1, px.max() - px.min() + 1
        ry, rx = (py.mean() - y0) / gh, (px.mean() - x0) / gw
        if not (PRINT_BAND[0] <= ry <= PRINT_BAND[1] and PRINT_BAND[0] <= rx <= PRINT_BAND[1]):
            continue
        if w < BIG_GRAPHIC_SPAN * gw and h < BIG_GRAPHIC_SPAN * gh:
            continue
        found.append(Graphic(comp, (px.mean() / k, py.mean() / k), h / k, w / k))
    return sorted(found, key=lambda g: -g.hi.sum())


def _graphic_quant(c: _Classified, g: Graphic) -> tuple[np.ndarray, np.ndarray]:
    """Median-cut a graphic's own photo pixels to a few colors: (palette (m, 3), hi-res index map, -1 off it)."""
    pix = c.hi_rgb[g.hi].astype(np.uint8)
    q = Image.fromarray(pix.reshape(1, -1, 3), "RGB").quantize(
        colors=GRAPHIC_COLORS, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    pal = np.array(q.getpalette()[: 3 * GRAPHIC_COLORS], np.uint8).reshape(-1, 3)
    qmap = np.full(g.hi.shape, -1)
    qmap[g.hi] = np.asarray(q)[0]
    return pal, qmap


def _ink(totals: list, fabric_hex: str) -> tuple:
    """Lettering color: of the graphic's colors covering at least a fifth of it, the one that
    contrasts most with the fabric (letter strokes, not their outline)."""
    from .palette import hex_to_rgb, lab_distance, rgb_to_lab

    fabric = rgb_to_lab(np.array(hex_to_rgb(fabric_hex), float))
    total = sum(t[1] for t in totals)
    major = [t for t in totals if t[1] >= 0.2 * total] or totals
    return max(major, key=lambda t: float(lab_distance(rgb_to_lab(np.array(t[0], float)), fabric)))[0]


def _graphic_colors(c: _Classified, g: Graphic, n: int, sprite_px: np.ndarray) -> tuple[np.ndarray, list]:
    """Per-sprite-pixel color for a graphic drawn from the photo: median-cut its own pixels to a
    few colors, then majority vote per block. Returns (n, n, 3) colors and [(rgb, pixel count)]."""
    k = WORK_FACTOR
    pal, qmap = _graphic_quant(c, g)
    counts = np.stack([(qmap == j).reshape(n, k, n, k).sum((1, 3)) for j in range(len(pal))], -1)
    best = counts.argmax(-1)
    totals = [(tuple(int(v) for v in pal[j]), int((best[sprite_px] == j).sum())) for j in range(len(pal))]
    return pal[best], sorted([t for t in totals if t[1]], key=lambda t: -t[1])


def _text_rows(text: str) -> list[str] | None:
    """3x5 bitmap of a word: 1px between letters, 2px for a space. None if nothing is drawable."""
    from .render import FONT_3x5

    cols: list[str] = []          # each entry is one 5-pixel column, top to bottom
    for ch in text:
        if ch == " ":
            cols += ["00000"] * 2
            continue
        bits = FONT_3x5.get(ch)
        if bits is None:
            continue
        if cols and cols[-1] != "00000":
            cols.append("00000")
        cols += ["".join(bits[r * 3 + c] for r in range(5)) for c in range(3)]
    while cols and cols[-1] == "00000":
        cols.pop()
    return ["".join(col[r] for col in cols) for r in range(5)] if cols else None


def text_fallbacks(text: str, graphic: str) -> list[str]:
    """Most to least faithful. Only a letter-style print may shrink to initials / one letter;
    a slogan that doesn't fit keeps the photo's own shape instead."""
    words = text.split()
    out = [text]
    if graphic == "letter":
        if len(words) > 1:
            out.append("".join(w[0] for w in words))
        out.append(words[0][0])
    return list(dict.fromkeys(out))


def _fabric_span(mask: np.ndarray, cx: float, cy: float, rows: int = 5) -> tuple[int, int]:
    """(left, right) of the fabric run under the glyph rows, narrowest row wins."""
    n = mask.shape[0]
    x0, y0 = int(np.clip(round(cx), 0, n - 1)), int(round(cy - rows / 2))
    left, right = 0, n - 1
    for y in range(max(y0, 0), min(y0 + rows, n)):
        if not mask[y, x0]:
            continue
        l = r = x0
        while l > 0 and mask[y, l - 1]:
            l -= 1
        while r < n - 1 and mask[y, r + 1]:
            r += 1
        left, right = max(left, l), min(right, r)
    return left, right


def choose_graphic(recipe, mask: np.ndarray, cx: float, cy: float, print_height: float | None,
                   margins: tuple[int, ...] = (2,)) -> tuple[list[str], int, str] | None:
    """(bitmap rows, scale, text drawn) for a big graphic's lettering, or None to draw the
    graphic from the photo instead.

    Chain: Gemma's full text -> initials -> first letter. Text must fit inside the fabric with
    `margin` px clear on each side; each candidate tries the margins in order before the chain
    moves on (a word 1px from the edge beats dropping to its first letter)."""
    text = (getattr(recipe, "extra", None) or {}).get("graphic_text")
    if not text and recipe.graphic == "letter":
        text = recipe.graphic_letter
    if not text or recipe.graphic not in ("letter", "text"):
        return None
    left, right = _fabric_span(mask, cx, cy)
    for cand in text_fallbacks(text, recipe.graphic):
        rows = _text_rows(cand)
        if rows is None:
            continue
        for margin in margins:
            for scale in (2, 1):
                if scale == 2 and (print_height is None or print_height < 9):
                    continue
                if len(rows[0]) * scale <= right - left + 1 - 2 * margin:
                    return rows, scale, cand
    return None


@dataclass
class _Analysis:
    c: _Classified
    win: np.ndarray           # cleaned regions: only primary / secondary survive outside graphics
    d_l: np.ndarray
    graphics: list
    g_px: list                # per graphic: (n, n) sprite pixels it covers


def _analyze(square: Image.Image, anchors: list[Anchor], opts: PixelArtOptions, recipe) -> _Analysis:
    c = _classify(square, anchors, opts)
    n, k = opts.sprite_size, WORK_FACTOR
    roles = [a.role for a in anchors]
    mask = c.mask
    win = c.win.copy()

    # Graphics: the photo finds the big ones; Gemma reads their lettering. Everything that
    # isn't fabric, Gemma-confirmed trim (secondary) or a big graphic is a small marking and
    # is painted over as fabric.
    graphics = find_big_graphics(c, n, recipe.pattern)
    g_px = [mask & (g.hi.reshape(n, k, n, k).mean((1, 3)) >= PRINT_COVERAGE) for g in graphics]
    in_graphic = np.zeros_like(mask)
    for gp, g in zip(g_px, graphics):
        in_graphic |= gp | g.hi.reshape(n, k, n, k).any((1, 3))
    win[mask & ~np.isin(win, [i for i, r in enumerate(roles) if r in ("primary", "secondary")])] = 0
    win[in_graphic] = 0                                      # repainted below
    win = _tidy_regions(win, mask, np.zeros_like(mask))
    d_l = np.where(win == c.win, c.d_l, 0.0)   # reassigned pixels: old color's fold reading is meaningless
    return _Analysis(c, win, d_l, graphics, g_px)


def render_combined(square: Image.Image, anchors: list[Anchor], opts: PixelArtOptions,
                    recipe) -> tuple[Image.Image, list[str], str | None]:
    from .palette import hex_to_rgb
    from .render import _pattern_color

    a = _analyze(square, anchors, opts, recipe)
    c, win, d_l, graphics, g_px = a.c, a.win, a.d_l, a.graphics, a.g_px
    n = opts.sprite_size
    snap_on = opts.snap_to_palette
    roles = [x.role for x in anchors]
    mask = c.mask

    def at(dx, dy):  # mask value of the neighbor at (x+dx, y+dy)
        p = np.pad(mask, 1, constant_values=False)
        return p[1 + dy:1 + dy + n, 1 + dx:1 + dx + n]

    shade_band = mask & (~at(1, 0) | ~at(0, 1))
    light_band = mask & (~at(-1, 0) | ~at(0, -1)) & ~shade_band

    ramps = [_sprite_ramp(a.hex, snap_on) for a in anchors]
    base_hex = [rp["base"] for rp in ramps]
    p_hex = base_hex[0]
    second = next((base_hex[i] for i, r in enumerate(roles) if r == "secondary"), None)
    pat_second = second or (ramps[0]["light"] if c.a_lab[0, 0] < 50 else ramps[0]["shade"])

    out = np.zeros((n, n, 4), np.uint8)
    for y, x in zip(*np.nonzero(mask)):
        i = win[y, x]
        base = base_hex[i]
        if i == 0 and recipe.pattern != "solid":
            base = _pattern_color(x, y, recipe.pattern, p_hex, pat_second, ramps[0], recipe.seed)
        rp = ramps[i] if base == base_hex[i] else _sprite_ramp(base, snap_on)
        t = _fold_threshold(c.a_lab[i, 0]) * 1.5   # only clear folds; flat fills read as pixel art
        if shade_band[y, x] or d_l[y, x] < -t:
            tone = "shade"
        elif light_band[y, x] or d_l[y, x] > t:
            tone = "light"
        else:
            tone = "base"
        out[y, x, :3] = hex_to_rgb(rp[tone])
    out[mask, 3] = 255

    drawn = []
    for gi, (g, gp) in enumerate(zip(graphics, g_px)):
        colors, totals = _graphic_colors(c, g, n, gp)
        chosen = choose_graphic(recipe, mask, *g.center, g.height) if gi == 0 else None
        if chosen is None:
            out[gp, :3] = colors[gp]                         # the photo's own shape and colors
            drawn.append("photo")
            continue
        # Lettering Gemma read, crisp, in the graphic's ink color.
        rows, scale, text = chosen
        ink = _ink(totals, p_hex)
        gh, gw = len(rows) * scale, len(rows[0]) * scale
        cx, cy = g.center
        left, top = int(round(cx - gw / 2)), int(round(cy - gh / 2))
        span_l, span_r = _fabric_span(mask, cx, cy, gh)
        left = int(np.clip(left, span_l + 2, max(span_l + 2, span_r - 1 - gw)))   # stay on the fabric
        for gy, row in enumerate(rows):
            for gx, bit in enumerate(row):
                if bit == "1":
                    for sy in range(scale):
                        for sx in range(scale):
                            x, y = left + gx * scale + sx, top + gy * scale + sy
                            if 0 <= x < n and 0 <= y < n and mask[y, x]:
                                out[y, x, :3] = ink
        drawn.append(text)

    # Bold 1px outline, darkest tone of whichever region it borders (like the template renderer).
    pad_win = np.pad(np.where(mask, win, -1), 1, constant_values=-1)
    for y, x in zip(*np.nonzero(~mask & (at(1, 0) | at(-1, 0) | at(0, 1) | at(0, -1)))):
        nbrs = [pad_win[1 + y + dy, 1 + x + dx] for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))]
        nbrs = [v for v in nbrs if v >= 0]
        out[y, x, :3] = hex_to_rgb(ramps[max(set(nbrs), key=nbrs.count)]["outline"])
        out[y, x, 3] = 255
    return Image.fromarray(out, "RGBA"), _palette_of(out), (", ".join(drawn) or None)


# ------------------------------------------------------------------ shaped --
# The combined analysis poured into the hand-drawn template shapes (templates.py), so every
# sprite in the wardrobe shares one silhouette per garment type. The template keeps its
# outline, shading and detail lines; the photo decides which template areas are fabric or
# trim and supplies the big graphic. render.py does all the drawing (three passes, then each
# pixel is taken from the pass that matches the photo).


def _box(m: np.ndarray) -> tuple[int, int, int, int]:
    ys, xs = np.nonzero(m)
    return xs.min(), ys.min(), xs.max() + 1, ys.max() + 1


def render_shaped(square: Image.Image, anchors: list[Anchor], opts: PixelArtOptions,
                  recipe) -> tuple[Image.Image, list[str], str | None]:
    from dataclasses import replace

    from .render import render_sprite
    from .templates import SIZE, TEMPLATES

    a = _analyze(square, anchors, opts, recipe)
    c, n, k = a.c, opts.sprite_size, WORK_FACTOR
    roles = [x.role for x in anchors]
    sec = roles.index("secondary") if "secondary" in roles else None

    tpl = TEMPLATES[recipe.subtype]
    grid = np.array([list(r) for r in tpl.rows])
    shape = grid != "."
    tx0, ty0, tx1, ty1 = _box(shape)
    px0, py0, px1, py1 = _box(c.mask)
    sx, sy = (px1 - px0) / (tx1 - tx0), (py1 - py0) / (ty1 - ty0)

    def photo_rect(x, y):  # template pixel -> its rectangle in analysis (sprite-res) coords
        return (px0 + (x - tx0) * sx, py0 + (y - ty0) * sy, px0 + (x + 1 - tx0) * sx, py0 + (y + 1 - ty0) * sy)

    def to_template(fx, fy):  # analysis coords -> template coords
        return tx0 + (fx - px0) / sx, ty0 + (fy - py0) / sy

    # Which template pixels the photo says are trim-colored.
    is_sec = np.zeros_like(shape)
    if sec is not None:
        for y, x in zip(*np.nonzero(shape)):
            fx0, fy0, fx1, fy1 = photo_rect(x, y)
            cx, cy = int(np.clip((fx0 + fx1) / 2, 0, n - 1)), int(np.clip((fy0 + fy1) / 2, 0, n - 1))
            is_sec[y, x] = c.mask[cy, cx] and a.win[cy, cx] == sec

    base = replace(recipe, graphic="none", accent=None, snap_to_palette=opts.snap_to_palette)
    p_hex, s_hex = anchors[0].hex, (anchors[sec].hex if sec is not None else None)
    as_drawn = np.asarray(render_sprite(replace(base, primary=p_hex, secondary=s_hex))).copy()
    trim_as_fabric = np.asarray(render_sprite(replace(base, primary=p_hex, secondary=None)))
    out = as_drawn
    t = grid == "t"
    as_fabric = t & ~is_sec                                   # template trim the photo shows as fabric
    pad = np.pad(as_fabric, 1)
    touches = pad[:-2, 1:-1] | pad[2:, 1:-1] | pad[1:-1, :-2] | pad[1:-1, 2:]
    as_fabric |= (grid == ".") & touches                       # ...and the outline drawn around it
    out[as_fabric] = trim_as_fabric[as_fabric]
    if s_hex:
        all_trim = np.asarray(render_sprite(replace(base, primary=s_hex, secondary=s_hex, pattern="solid")))
        sel = np.isin(grid, ["#", "d"]) & is_sec               # fabric/detail the photo shows as trim
        out[sel] = all_trim[sel]

    drawn = []
    fabric = grid == "#"
    for gi, g in enumerate(a.graphics):
        pal, qmap = _graphic_quant(c, g)
        counts = np.array([(qmap == j).sum() for j in range(len(pal))])
        totals = sorted([(tuple(int(v) for v in pal[j]), int(counts[j])) for j in range(len(pal)) if counts[j]],
                        key=lambda t: -t[1])
        gx, gy = to_template(*g.center)
        chosen = (choose_graphic(recipe, fabric, gx, gy, g.height / sy, margins=(2, 1))
                  if gi == 0 else None)
        if chosen:
            rows, scale, text = chosen
            ink = _ink(totals, p_hex)
            gh, gw = len(rows) * scale, len(rows[0]) * scale
            left, top = int(round(gx - gw / 2)), int(round(gy - gh / 2))
            span_l, span_r = _fabric_span(fabric, gx, gy, gh)
            left = int(np.clip(left, span_l + 1, max(span_l + 1, span_r - gw)))
            for ry, row in enumerate(rows):
                for rx, bit in enumerate(row):
                    if bit == "1":
                        for dy in range(scale):
                            for dx in range(scale):
                                x, y = left + rx * scale + dx, top + ry * scale + dy
                                if 0 <= x < SIZE and 0 <= y < SIZE and fabric[y, x]:
                                    out[y, x, :3] = ink
            drawn.append(text)
            continue
        # Photo-drawn: each template pixel takes the graphic's majority color in its photo rectangle.
        hit = False
        for y, x in zip(*np.nonzero(fabric)):
            fx0, fy0, fx1, fy1 = (int(round(v * k)) for v in photo_rect(x, y))
            block = qmap[max(fy0, 0):max(fy1, fy0 + 1), max(fx0, 0):max(fx1, fx0 + 1)]
            if block.size and (block >= 0).mean() >= PRINT_COVERAGE:
                out[y, x, :3] = pal[np.bincount(block[block >= 0]).argmax()]
                hit = True
        if hit:
            drawn.append("photo")
    return Image.fromarray(out, "RGBA"), _palette_of(out), (", ".join(drawn) or None)


def generate_pixel_art(cutout: Image.Image, opts: PixelArtOptions | None = None,
                       anchors: list[Anchor] | None = None, recipe=None) -> dict:
    """Full photo -> sprite step on an existing cutout (see segment.cut_out_garment).
    combined needs anchors (see anchors_from_spec) and the SpriteRecipe; hybrid needs anchors."""
    opts = opts or PixelArtOptions()
    square = normalize_and_center(cutout, opts)
    if opts.mode in ("shaped", "combined", "hybrid") and not anchors:
        raise ValueError(f"{opts.mode} mode needs anchor colors from the garment spec")
    if opts.mode in ("shaped", "combined") and recipe is None:
        raise ValueError(f"{opts.mode} mode needs the garment's SpriteRecipe")
    if opts.mode == "shaped":
        from dataclasses import replace

        from .templates import SIZE
        sprite, palette, drawn = render_shaped(square, anchors, opts, recipe)
        # Output is the template canvas; the analysis ran at sprite_size. Same preview scale.
        out_opts = replace(opts, sprite_size=SIZE, preview_size=SIZE * (opts.preview_size // opts.sprite_size))
        master, preview = export_sprite(sprite, out_opts)
        settings = {**opts.to_dict(), "analysis_size": opts.sprite_size,
                    "sprite_size": SIZE, "preview_size": out_opts.preview_size,
                    "anchors": [asdict(x) for x in anchors]}
        return {"sprite": master, "preview": preview, "palette": palette, "settings": settings,
                "graphic_drawn": drawn}
    if opts.mode == "combined":
        sprite, palette, drawn = render_combined(square, anchors, opts, recipe)
    elif opts.mode == "hybrid":
        sprite, palette = render_hybrid(square, anchors, opts)
    elif opts.mode == "photo":
        sprite, palette = pixelate_and_quantize(square, opts)
    else:
        raise ValueError(f"unknown pixel-art mode {opts.mode!r}")
    master, preview = export_sprite(sprite, opts)
    settings = opts.to_dict()
    if anchors and opts.mode != "photo":
        settings["anchors"] = [asdict(a) for a in anchors]
    out = {"sprite": master, "preview": preview, "palette": palette, "settings": settings}
    if opts.mode == "combined":
        out["graphic_drawn"] = drawn       # per big graphic: its text ("PITT", "P") or "photo"; None
    return out
