"""any image -> PNG -> cutout + measured colors -> Gemma (via Pydantic AI) -> GarmentSpec -> sprite

CLI:
  python -m wardrobe_pixels.generate photos/* --out out                  # Gemma via API key
  python -m wardrobe_pixels.generate IMG_0042.HEIC --provider ollama
  python -m wardrobe_pixels.generate hoodie.webp --provider test --hint hoodie   # offline
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from .agent import GemmaSpriter, SpriteGenerationError
from .colors import extract_colors
from .gallery import build as build_gallery
from .ingest import UnsupportedImage, load_image, to_png_bytes
from .palette import snap
from .pixelate import PixelArtOptions, anchors_from_spec, generate_pixel_art
from .render import SpriteRecipe, render_sprite
from .segment import cut_out_garment, cut_out_worn_garment
from .spec import spec_to_recipe

SPRITE_SCALE = 8


@dataclass
class GeneratedItem:
    item: dict                 # JSON-ready record for the frontend / database
    sprite: Image.Image        # 32x32 RGBA
    sprite_large: Image.Image  # scaled up, nearest-neighbor
    cutout: Image.Image        # background-removed photo
    pixel_art: dict | None = None  # photo-derived sprite (pixelate.py), if requested
    original: bytes | None = None  # the upload exactly as received (never overwritten)


def _original_ext(data: bytes) -> str:
    try:
        return (Image.open(io.BytesIO(data)).format or "bin").lower().replace("jpeg", "jpg")
    except Exception:
        return "bin"


def recipe_from_item(item: dict) -> SpriteRecipe:
    """Re-render after the user edits an item in the UI. No model call."""
    c = item["colors"]
    return SpriteRecipe(subtype=item["subtype"], primary=c["primary"], secondary=c["secondary"],
                        accent=c["accent"], pattern=item["pattern"], graphic=item["graphic"],
                        graphic_letter=item["graphic_letter"], seed=item["id"],
                        snap_to_palette=item.get("snap_to_palette", True),
                        extra={"graphic_text": item["graphic_text"]} if item.get("graphic_text") else {})


async def generate_item(source: str | Path | bytes, spriter: GemmaSpriter, *, hint: str | None = None,
                        snap_to_palette: bool = True, filename: str | None = None,
                        pixel_art: PixelArtOptions | None = None) -> GeneratedItem:
    data = Path(source).read_bytes() if isinstance(source, (str, Path)) else bytes(source)
    item_id = hashlib.sha1(data).hexdigest()[:10]

    image = load_image(data)                      # any format -> upright RGBA
    cutout, warnings = cut_out_garment(image)
    colors = extract_colors(cutout)
    png = to_png_bytes(cutout, flatten_on=(255, 255, 255))   # what Gemma sees

    spec = await spriter.describe(png, colors, hint)
    recipe = spec_to_recipe(spec, colors, seed=item_id, snap_to_palette=snap_to_palette)

    px_colors = colors
    if spec.worn:
        # Gemma saw a person: re-cut just the clothing region for its category, and
        # re-measure so skin/hair can't become detail colors in the pixel art.
        garment, notes = cut_out_worn_garment(image, spec.category)
        warnings.extend(notes)
        if garment is not None:
            cutout, px_colors = garment, extract_colors(garment)

    item = {
        "id": item_id,
        "name": spec.name,
        "category": spec.category,
        "subtype": spec.subtype,
        "pattern": spec.pattern,
        "graphic": spec.graphic,
        "graphic_letter": spec.graphic_letter,
        "graphic_text": spec.graphic_text,
        "colors": {"primary": recipe.primary, "secondary": recipe.secondary, "accent": recipe.accent},
        "palette_colors": {k: (snap(v) if v else None) for k, v in
                           {"primary": recipe.primary, "secondary": recipe.secondary,
                            "accent": recipe.accent}.items()},
        "measured_colors": colors,
        "warmth": spec.warmth,
        "formality": spec.formality,
        "vibe_tags": spec.vibe_tags,
        "worn": spec.worn,
        "status": "clean",
        "snap_to_palette": snap_to_palette,
        "source_photo": filename or (Path(source).name if isinstance(source, (str, Path)) else None),
        "model": f"{spriter.provider}:{spriter.model_name}",
        "warnings": warnings,
    }
    px = None
    if pixel_art:
        # Gemma's spec + the photo's pixels (pixelate.py). Failure keeps the template sprite.
        try:
            px = generate_pixel_art(cutout, pixel_art, anchors_from_spec(item["colors"], px_colors),
                                    recipe=recipe)
            item["pixel_art"] = {"status": "ready", "palette": px["palette"], "settings": px["settings"],
                                 **({"graphic_drawn": px["graphic_drawn"]} if "graphic_drawn" in px else {})}
        except ValueError as e:
            warnings.append(f"pixel art failed: {e}")
            item["pixel_art"] = {"status": "failed", "error": str(e)}
    return GeneratedItem(item=item, sprite=render_sprite(recipe),
                         sprite_large=render_sprite(recipe, scale=SPRITE_SCALE), cutout=cutout,
                         pixel_art=px, original=data)


def save_item(gen: GeneratedItem, out_dir: str | Path) -> dict:
    out = Path(out_dir)
    (out / "sprites").mkdir(parents=True, exist_ok=True)
    (out / "cutouts").mkdir(parents=True, exist_ok=True)
    i = gen.item["id"]
    item = {**gen.item, "sprite": f"sprites/{i}.png", "sprite_large": f"sprites/{i}@{SPRITE_SCALE}x.png",
            "cutout": f"cutouts/{i}.png"}
    gen.sprite.save(out / item["sprite"])
    gen.sprite_large.save(out / item["sprite_large"])
    gen.cutout.save(out / item["cutout"])
    if gen.original is not None:
        (out / "originals").mkdir(exist_ok=True)
        item["original"] = f"originals/{i}.{_original_ext(gen.original)}"
        (out / item["original"]).write_bytes(gen.original)
    if gen.pixel_art:
        st = gen.pixel_art["settings"]
        stem = f"sprites/{i}_{st['mode']}{st['sprite_size']}"
        scale = st["preview_size"] // st["sprite_size"]
        item["pixel_art"] = {**item["pixel_art"], "sprite": f"{stem}.png", "preview": f"{stem}@{scale}x.png"}
        gen.pixel_art["sprite"].save(out / item["pixel_art"]["sprite"])
        gen.pixel_art["preview"].save(out / item["pixel_art"]["preview"])
    return item


async def _run(args):
    spriter = GemmaSpriter(provider=args.provider, model=args.model, output_mode=args.output_mode)
    out = Path(args.out)
    manifest = out / "wardrobe.json"
    wardrobe = {it["id"]: it for it in json.loads(manifest.read_text())} if manifest.exists() else {}

    px_opts = None if args.pixel_art == "off" else PixelArtOptions(
        mode=args.pixel_art, sprite_size=args.px_size, preview_size=args.px_size * SPRITE_SCALE,
        palette_colors=args.px_colors, dither=args.px_dither, outline=args.px_outline,
        snap_to_palette=args.px_snap)
    sem = asyncio.Semaphore(args.concurrency)  # free tiers rate-limit; keep this small

    async def one(path: str):
        async with sem:
            try:
                gen = await generate_item(path, spriter, hint=args.hint, snap_to_palette=not args.no_snap,
                                          pixel_art=px_opts)
            except (UnsupportedImage, SpriteGenerationError, OSError) as e:
                print(f"✗ {path}: {e}")
                return
            item = save_item(gen, out)
            wardrobe[item["id"]] = item
            note = f"  ({'; '.join(item['warnings'])})" if item["warnings"] else ""
            print(f"✓ {path} -> {item['name']} [{item['subtype']}, {item['pattern']}]{note}")

    await asyncio.gather(*(one(p) for p in args.photos))
    out.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(list(wardrobe.values()), indent=2))
    print(f"wrote {manifest} ({len(wardrobe)} items)")
    print(f"wrote {build_gallery(out)}")


def main():
    ap = argparse.ArgumentParser(description="Clothing photos -> pixel-art sprites with Gemma 4")
    ap.add_argument("photos", nargs="+", help="any image format: jpg, png, webp, heic, gif, bmp, tiff...")
    ap.add_argument("--out", default="out")
    ap.add_argument("--provider", default="google", choices=["google", "ollama", "test"])
    ap.add_argument("--model", default=None)
    ap.add_argument("--output-mode", default="prompted", choices=["prompted", "tool", "native"])
    ap.add_argument("--hint", default=None, help="optional garment hint, e.g. hoodie")
    ap.add_argument("--no-snap", action="store_true", help="keep exact photo colors")
    ap.add_argument("--concurrency", type=int, default=2)
    ap.add_argument("--pixel-art", default="shaped", choices=["shaped", "combined", "hybrid", "photo", "off"],
                    help="photo-derived sprite next to the template one: shaped = combined analysis in the "
                         "template shapes (default), combined = photo silhouette in the template style, "
                         "hybrid = detailed photo render, photo = plain quantize, off = template sprite only")
    ap.add_argument("--px-size", type=int, default=40,
                    help="analysis resolution (shaped/combined: 32-48), sprite resolution (hybrid: ~96)")
    ap.add_argument("--px-colors", type=int, default=16, help="photo mode only")
    ap.add_argument("--px-dither", default="none", choices=["none", "ordered"], help="photo mode only")
    ap.add_argument("--px-outline", action="store_true", help="1px dark outline around the silhouette")
    ap.add_argument("--px-snap", action="store_true", help="hybrid: snap to the shared game palette")
    asyncio.run(_run(ap.parse_args()))


if __name__ == "__main__":
    main()
