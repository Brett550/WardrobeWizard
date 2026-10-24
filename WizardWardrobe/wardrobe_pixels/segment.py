"""Cut the garment out of the photo.

Order of preference:
  1. The image already has transparency (user uploaded a cutout PNG).
  2. rembg (pip install rembg) - works on messy real-world photos.
  3. Fallback: assumes a fairly plain background (bed, floor, wall) and
     separates the garment by color distance from the image border.
"""
from __future__ import annotations

import numpy as np
from PIL import Image

from .palette import lab_distance, rgb_to_lab

WORK_SIZE = 512


def _resize(img: Image.Image) -> Image.Image:
    img = img.copy()
    img.thumbnail((WORK_SIZE, WORK_SIZE), Image.LANCZOS)
    return img


def _has_real_alpha(img: Image.Image) -> bool:
    if img.mode != "RGBA":
        return False
    a = np.asarray(img)[..., 3]
    return (a < 128).mean() > 0.05


def _otsu(values: np.ndarray) -> float:
    hist, edges = np.histogram(values, bins=128)
    hist = hist.astype(np.float64)
    centers = (edges[:-1] + edges[1:]) / 2
    w0 = np.cumsum(hist)
    w1 = w0[-1] - w0
    m0 = np.cumsum(hist * centers) / np.maximum(w0, 1)
    m1 = (np.sum(hist * centers) - np.cumsum(hist * centers)) / np.maximum(w1, 1)
    between = w0 * w1 * (m0 - m1) ** 2
    return float(centers[np.argmax(between)])


def _clean_mask(mask: np.ndarray, dist: np.ndarray, noise: float) -> np.ndarray:
    try:
        from scipy import ndimage
    except ImportError:
        return mask
    mask = ndimage.binary_opening(mask, iterations=2)
    labels, n = ndimage.label(mask)
    if n > 1:
        # Keep every sizable piece: stripes in a background-like color can
        # split one garment into several bands.
        sizes = ndimage.sum(mask, labels, range(1, n + 1))
        keep = np.flatnonzero(sizes >= 0.05 * sizes.max()) + 1
        mask = np.isin(labels, keep)
    # Bridge the gaps between those pieces, then fill everything enclosed.
    closed = ndimage.binary_closing(np.pad(mask, 12), iterations=10)[12:-12, 12:-12]
    closed = ndimage.binary_fill_holes(closed)
    # Closing also fills concave gaps (armpits, between legs) with background.
    # Only accept added pixels that are measurably different from the background.
    added = closed & ~mask
    mask = mask | (added & (dist > noise * 1.5))
    mask = ndimage.binary_opening(mask, iterations=1)
    mask = ndimage.binary_fill_holes(mask)
    labels, n = ndimage.label(mask)
    if n > 1:
        sizes = ndimage.sum(mask, labels, range(1, n + 1))
        mask = labels == (int(np.argmax(sizes)) + 1)
    return mask


def _fallback_cutout(img: Image.Image) -> Image.Image:
    rgb = np.asarray(img.convert("RGB"), dtype=np.float64)
    lab = rgb_to_lab(rgb)
    b = 6
    border = np.concatenate([lab[:b].reshape(-1, 3), lab[-b:].reshape(-1, 3),
                             lab[:, :b].reshape(-1, 3), lab[:, -b:].reshape(-1, 3)])
    bg = np.median(border, axis=0)
    # Down-weight lightness so soft shadows on the background don't count as garment.
    dist = lab_distance(lab, bg, l_weight=0.7)
    border_dist = lab_distance(border, bg, l_weight=0.7)
    noise = float(np.percentile(border_dist, 95))
    thr = max(_otsu(dist), 12.0, noise * 2)
    mask = _clean_mask(dist > thr, dist, noise)
    alpha = (mask * 255).astype(np.uint8)
    out = img.convert("RGBA")
    out.putalpha(Image.fromarray(alpha))
    return out


def cut_out_garment(img: Image.Image) -> tuple[Image.Image, list[str]]:
    """Returns (RGBA cutout cropped to the garment, warnings)."""
    warnings: list[str] = []
    img = _resize(img)

    if _has_real_alpha(img):
        out = img.convert("RGBA")
    else:
        try:
            from rembg import remove  # type: ignore
            out = remove(img.convert("RGB")).convert("RGBA")
        except ImportError:
            warnings.append("rembg not installed; using plain-background fallback")
            out = _fallback_cutout(img)

    alpha = np.asarray(out)[..., 3]
    coverage = (alpha > 128).mean()
    if coverage < 0.03:
        warnings.append("garment barely detected; try a plainer background")
    elif coverage > 0.95:
        warnings.append("background not removed; colors may include the background")

    bbox = Image.fromarray(((alpha > 128) * 255).astype(np.uint8)).getbbox()
    if bbox:
        out = out.crop(bbox)
    return out, warnings


CLOTH_REGIONS = {"top": "upper", "bottom": "lower"}   # template category -> u2net_cloth_seg class
_cloth_session = None


def cut_out_worn_garment(img: Image.Image, category: str) -> tuple[Image.Image | None, list[str]]:
    """Garment-only cutout when someone is wearing it (plain rembg keeps the whole person).

    Gemma's category picks the clothing region. Returns (None, warnings) when this can't
    help, so the caller keeps the normal cutout."""
    region = CLOTH_REGIONS.get(category)
    if region is None:
        return None, [f"worn {category}: no clothing-only segmentation, the person may show in the sprite"]
    global _cloth_session
    try:
        from rembg import new_session  # type: ignore
        _cloth_session = _cloth_session or new_session("u2net_cloth_seg")
    except ImportError:
        return None, ["worn garment: install rembg to cut out just the clothing"]

    img = _resize(img)
    mask = np.asarray(_cloth_session.predict(img.convert("RGB"), cc=region)[0].resize(img.size)) >= 128
    try:
        from scipy import ndimage
        labels, n = ndimage.label(mask)
        if n > 1:  # stray fragments (undershirt hem, other clothes) -> keep the garment itself
            sizes = ndimage.sum(mask, labels, range(1, n + 1))
            mask = labels == (int(np.argmax(sizes)) + 1)
        mask = ndimage.binary_fill_holes(mask)
    except ImportError:
        pass
    if mask.mean() < 0.03:
        return None, ["worn garment: clothing segmentation found nothing, the person may show in the sprite"]
    out = img.convert("RGBA")
    out.putalpha(Image.fromarray((mask * 255).astype(np.uint8)))
    return out.crop(Image.fromarray((mask * 255).astype(np.uint8)).getbbox()), []


def on_white(rgba: Image.Image) -> Image.Image:
    """Flatten a cutout onto white (what we send to Gemma)."""
    bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    bg.alpha_composite(rgba)
    return bg.convert("RGB")
