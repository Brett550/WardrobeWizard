"""Build the demo wardrobe: 8 hats, tops, bottoms, socks and shoes, rendered with the real pipeline.

  python -m wardrobe_pixels.demo_wardrobe --out demo
  -> demo/wardrobe.json, demo/sprites/*.png (+ @8x), demo/sheet_<category>.png, demo/sheet_all.png

Each entry uses the same item format as generate.py, so the front end and backend can load it directly.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from PIL import Image, ImageDraw

from .palette import snap
from .render import SpriteRecipe, render_sprite
from .templates import TEMPLATES

# name, subtype, primary, secondary, accent, pattern, graphic, letter, warmth, formality, tags
ITEMS = [
    # ---- hats
    ("Black Ball Cap", "cap", "#1e1e1e", None, "#ffffff", "solid", "logo", None, 2, 1, ["streetwear", "basic"]),
    ("Red Star Fitted", "cap", "#e43b44", None, "#ffffff", "solid", "star", None, 2, 1, ["bold", "sporty"]),
    ("Khaki Dad Hat", "cap", "#d9c9a3", None, None, "solid", "none", None, 2, 2, ["campus", "basic"]),
    ("Navy Trucker", "cap", "#1f2a52", "#ffffff", "#ffffff", "solid", "letter", "K", 2, 1, ["campus", "streetwear"]),
    ("Grey Knit Beanie", "beanie", "#8a8a8a", "#1f2a52", None, "solid", "none", None, 4, 1, ["cozy", "comfy"]),
    ("Mustard Beanie", "beanie", "#feae34", None, None, "solid", "none", None, 4, 1, ["cozy", "bold"]),
    ("Olive Bucket Hat", "bucket", "#6f7d3c", None, None, "solid", "none", None, 2, 1, ["campus", "streetwear"]),
    ("Picnic Bucket Hat", "bucket", "#e43b44", "#ffffff", None, "checkered", "none", None, 2, 1, ["bold"]),
    # ---- tops
    ("Plain White Tee", "tshirt", "#ffffff", None, None, "solid", "none", None, 2, 2, ["basic", "dressy"]),
    ("Black Graphic Tee", "tshirt", "#1e1e1e", None, "#fee761", "solid", "text", None, 2, 1, ["streetwear", "bold"]),
    ("Sunny Star Tee", "tshirt", "#fee761", None, "#e43b44", "solid", "star", None, 2, 1, ["bold", "sporty"]),
    ("Candy Stripe Long Sleeve", "longsleeve", "#e43b44", "#ffffff", None, "striped", "none", None, 3, 1, ["bold", "campus"]),
    ("Forest Flannel", "longsleeve", "#3e8948", "#193c3e", None, "plaid", "none", None, 3, 3, ["cozy", "dressy"]),
    ("Navy Varsity Crewneck", "longsleeve", "#1f2a52", None, "#ffffff", "solid", "letter", "A", 4, 2, ["campus", "cozy"]),
    ("Heather Grey Hoodie", "hoodie", "#8a8a8a", None, None, "solid", "none", None, 4, 1, ["comfy", "sporty"]),
    ("Lilac Hoodie", "hoodie", "#b55088", None, "#ffffff", "solid", "heart", None, 4, 1, ["comfy", "bold"]),
    # ---- bottoms
    ("Classic Blue Jeans", "pants", "#4a6a9c", None, None, "denim", "none", None, 3, 2, ["campus", "basic"]),
    ("Black Jeans", "pants", "#3a3a3a", None, None, "denim", "none", None, 3, 3, ["streetwear", "dressy"]),
    ("Khaki Chinos", "pants", "#d9c9a3", None, None, "solid", "none", None, 3, 3, ["dressy", "basic"]),
    ("Grey Sweatpants", "pants", "#8a8a8a", "#5e5e5e", None, "solid", "none", None, 3, 1, ["comfy", "sporty"]),
    ("Olive Cargo Pants", "pants", "#4b5a2a", None, None, "solid", "none", None, 3, 1, ["streetwear", "campus"]),
    ("Denim Shorts", "shorts", "#4a6a9c", None, None, "denim", "none", None, 1, 1, ["campus", "sporty"]),
    ("Navy Gym Shorts", "shorts", "#1f2a52", "#ffffff", None, "solid", "none", None, 1, 1, ["sporty"]),
    ("Tan Plaid Shorts", "shorts", "#b9a77c", "#733e39", None, "plaid", "none", None, 1, 2, ["dressy", "campus"]),
    # ---- socks
    ("White Crew Socks", "socks", "#ffffff", "#c0cbdc", None, "solid", "none", None, 3, 1, ["basic"]),
    ("Black Dress Socks", "socks", "#262b44", None, None, "solid", "none", None, 3, 3, ["dressy"]),
    ("Grey Athletic Socks", "socks", "#b4b4b4", "#e43b44", None, "solid", "none", None, 3, 1, ["sporty"]),
    ("Red Stripe Socks", "socks", "#e43b44", "#ffffff", None, "striped", "none", None, 3, 1, ["bold"]),
    ("Navy Dot Socks", "socks", "#1f2a52", "#ffffff", None, "polka_dot", "none", None, 3, 2, ["campus"]),
    ("Mustard Socks", "socks", "#feae34", "#733e39", None, "solid", "none", None, 3, 1, ["bold", "cozy"]),
    ("Green Check Socks", "socks", "#3e8948", "#d9c9a3", None, "checkered", "none", None, 3, 2, ["campus"]),
    ("Pink Flower Socks", "socks", "#f6757a", "#ffffff", None, "floral", "none", None, 3, 1, ["bold"]),
    # ---- shoes
    ("White Court Sneakers", "sneakers", "#ffffff", "#dcdcdc", None, "solid", "none", None, 3, 2, ["basic", "dressy"]),
    ("Black Runners", "sneakers", "#1e1e1e", "#ffffff", None, "solid", "none", None, 3, 1, ["sporty"]),
    ("Grey Trainers", "sneakers", "#8a8a8a", "#ffffff", None, "solid", "none", None, 3, 1, ["sporty", "basic"]),
    ("Green Low-Tops", "sneakers", "#3e8948", "#ffffff", None, "solid", "none", None, 3, 1, ["bold", "campus"]),
    ("Red Canvas High-Tops", "hightops", "#e43b44", "#ffffff", None, "solid", "none", None, 3, 1, ["bold", "streetwear"]),
    ("Navy Canvas High-Tops", "hightops", "#1f2a52", "#ffffff", None, "solid", "none", None, 3, 1, ["campus"]),
    ("White High-Tops", "hightops", "#ffffff", "#e43b44", None, "solid", "none", None, 3, 2, ["streetwear", "basic"]),
    ("Brown Work Boots", "hightops", "#733e39", "#d9c9a3", None, "solid", "none", None, 4, 3, ["cozy", "dressy"]),
]

CATEGORY_ORDER = ["hat", "top", "bottom", "socks", "shoes"]
SCALE = 8


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def build(out_dir: str | Path) -> list[dict]:
    out = Path(out_dir)
    (out / "sprites").mkdir(parents=True, exist_ok=True)
    items = []
    for (name, subtype, p, s, a, pat, g, letter, warmth, formality, tags) in ITEMS:
        item_id = slug(name)
        recipe = SpriteRecipe(subtype, p, s, a, pattern=pat, graphic=g, graphic_letter=letter, seed=item_id)
        render_sprite(recipe).save(out / f"sprites/{item_id}.png")
        render_sprite(recipe, scale=SCALE).save(out / f"sprites/{item_id}@{SCALE}x.png")
        items.append({
            "id": item_id, "name": name, "category": TEMPLATES[subtype].category, "subtype": subtype,
            "pattern": pat, "graphic": g, "graphic_letter": letter,
            "colors": {"primary": p, "secondary": s, "accent": a},
            "palette_colors": {"primary": snap(p), "secondary": snap(s) if s else None,
                               "accent": snap(a) if a else None},
            "warmth": warmth, "formality": formality, "vibe_tags": tags, "status": "clean",
            "snap_to_palette": True, "sprite": f"sprites/{item_id}.png",
            "sprite_large": f"sprites/{item_id}@{SCALE}x.png", "source_photo": None, "model": "demo",
        })
    (out / "wardrobe.json").write_text(json.dumps(items, indent=2))
    _sheets(items, out)
    return items


def _sheets(items: list[dict], out: Path, cell: int = 32 * 5, label_h: int = 26):
    bg = (255, 255, 255, 255)
    rows = []
    for cat in CATEGORY_ORDER:
        group = [i for i in items if i["category"] == cat]
        sheet = Image.new("RGBA", (cell * len(group), cell + label_h), bg)
        draw = ImageDraw.Draw(sheet)
        for k, it in enumerate(group):
            sprite = Image.open(out / it["sprite"]).resize((cell, cell), Image.NEAREST)
            sheet.alpha_composite(sprite, (k * cell, 0))
            text = it["name"] if len(it["name"]) <= 22 else it["name"][:21] + "…"
            w = draw.textlength(text)
            draw.text((k * cell + (cell - w) / 2, cell + 4), text, fill=(24, 20, 37, 255))
        sheet.save(out / f"sheet_{cat}.png")
        rows.append(sheet)
    full = Image.new("RGBA", (max(r.width for r in rows), sum(r.height for r in rows)), bg)
    y = 0
    for r in rows:
        full.alpha_composite(r, (0, y))
        y += r.height
    full.save(out / "sheet_all.png")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="demo")
    items = build(ap.parse_args().out)
    print(f"built {len(items)} items")
