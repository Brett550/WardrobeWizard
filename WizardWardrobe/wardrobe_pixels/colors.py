"""Measure the garment's real colors from its pixels (Gemma is bad at exact hex)."""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter

from .palette import lab_distance, rgb_to_hex, rgb_to_lab


def _kmeans(x: np.ndarray, k: int, iters: int = 25, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    # k-means++ init
    centers = [x[rng.integers(len(x))]]
    for _ in range(1, k):
        d = np.min([np.sum((x - c) ** 2, axis=1) for c in centers], axis=0)
        centers.append(x[rng.choice(len(x), p=d / d.sum())] if d.sum() > 0 else x[rng.integers(len(x))])
    centers = np.array(centers)
    for _ in range(iters):
        labels = np.argmin(((x[:, None, :] - centers[None]) ** 2).sum(-1), axis=1)
        new = np.array([x[labels == i].mean(0) if np.any(labels == i) else centers[i] for i in range(k)])
        if np.allclose(new, centers, atol=0.1):
            break
        centers = new
    return centers, labels


def _seg_dist(p: np.ndarray, a: np.ndarray, b: np.ndarray) -> float:
    ab = b - a
    t = np.clip(np.dot(p - a, ab) / max(np.dot(ab, ab), 1e-9), 0, 1)
    return float(np.linalg.norm(p - (a + t * ab)))


def _is_blend(c: dict, bigger: list[dict], tol: float = 12.0) -> bool:
    """A small cluster sitting between two bigger ones is anti-aliasing, not a real color
    (e.g. pink pixels where red and white stripes meet)."""
    if len(bigger) < 2:
        return False
    total = c["n"] + sum(b["n"] for b in bigger)
    if c["n"] / total > 0.08:
        return False
    return any(_seg_dist(c["lab"], bigger[i]["lab"], bigger[j]["lab"]) < tol
               for i in range(len(bigger)) for j in range(i + 1, len(bigger)))


def extract_colors(cutout: Image.Image, k: int = 6, min_share: float = 0.02,
                   merge_dist: float = 14.0) -> list[dict]:
    """Returns [{'hex': '#rrggbb', 'share': 0.61}, ...] sorted by share.

    Clusters that differ mostly in lightness (the same fabric in light and
    shadow) are merged so 'navy' and 'navy in shadow' count as one color.
    """
    rgba = cutout.convert("RGBA")
    # Shave 2px off the edge so pixels blended with the background don't count.
    alpha = rgba.getchannel("A").filter(ImageFilter.MinFilter(5))
    arr = np.asarray(rgba)
    inner = np.asarray(alpha) > 128
    if inner.sum() < 50:
        inner = arr[..., 3] > 128
    px = arr[inner][:, :3].astype(np.float64)
    if len(px) == 0:
        return [{"hex": "#808080", "share": 1.0}]
    if len(px) > 20000:
        px = px[np.random.default_rng(0).choice(len(px), 20000, replace=False)]

    lab = rgb_to_lab(px)
    k = min(k, len(np.unique(px, axis=0)))
    centers, labels = _kmeans(lab, k)

    clusters = []
    for i in range(k):
        sel = labels == i
        if sel.any():
            clusters.append({"lab": lab[sel].mean(0), "rgb": px[sel].mean(0), "n": int(sel.sum())})

    merged = True
    while merged and len(clusters) > 1:
        merged = False
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                a, b = clusters[i], clusters[j]
                if lab_distance(a["lab"], b["lab"], l_weight=0.5) < merge_dist:
                    n = a["n"] + b["n"]
                    big, small = (a, b) if a["n"] >= b["n"] else (b, a)
                    # Keep the dominant cluster's color rather than averaging toward shadow.
                    clusters[i] = {"lab": big["lab"], "rgb": big["rgb"], "n": n}
                    clusters.pop(j)
                    merged = True
                    break
            if merged:
                break

    clusters.sort(key=lambda c: -c["n"])
    clusters = [c for i, c in enumerate(clusters) if not _is_blend(c, clusters[:i])]

    total = sum(c["n"] for c in clusters)
    kept = []
    for c in clusters:
        share = c["n"] / total
        # Small prints (a chest logo) are tiny but very different from the fabric: keep them.
        distinct = all(lab_distance(c["lab"], k["lab"]) > 30 for k in kept)
        if share >= min_share or (share >= 0.004 and distinct):
            kept.append(c)
    kept = kept or clusters[:1]
    return [{"hex": rgb_to_hex(c["rgb"]), "share": round(c["n"] / total, 3)} for c in kept]
