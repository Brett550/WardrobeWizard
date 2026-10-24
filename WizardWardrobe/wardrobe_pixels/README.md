# wardrobe_pixels

Any clothing photo -> pixel sprites, with Gemma 4 as the eyes and Pydantic AI as the harness.
Every item gets two sprites: a 32x32 **template** sprite (drawn from Gemma's description) and a
32x32 **shaped** sprite: the same template silhouette, filled from the photo. Real colors, which
template areas are fabric vs trim (cuffs, hem, hood lining), and the big graphic, with
Gemma's lettering. `--pixel-art combined` gives the free-form version (the photo's own silhouette).

```
upload (jpg/png/webp/heic/gif/bmp/tiff/svg)
  └─ ingest.py      normalize to upright RGBA, encode PNG
  └─ segment.py     cut out the garment
  └─ colors.py      measure real fabric colors (k-means)
  └─ agent.py       Pydantic AI Agent -> Gemma 4 -> GarmentSpec (validated, auto-retried)
  └─ render.py      template + palette swap + pattern + shading -> sprite PNG
  └─ segment.py     if Gemma says worn=true: re-cut just the top/bottom (rembg u2net_cloth_seg)
  └─ pixelate.py    analysis: photo regions + big graphics + Gemma's text -> shaped 32x32 template sprite
  └─ gallery.py     out/index.html wardrobe grid
```

Gemma never draws pixels. It fills in `GarmentSpec` (spec.py), and the renderers draw.

### Shaped sprites (pixelate.py, the default)

The combined analysis below runs at 40x40, then is poured into the template for Gemma's subtype.
The photo's garment box is mapped onto the template's box; each template pixel looks up the
photo region there. render.py draws three passes (as-is, trim as fabric, everything in the trim
color) and each pixel is taken from the pass that matches the photo, so the template's outline,
shading and detail lines stay exact. The big graphic is mapped in the same way (lettering via
the text chain, 1px margin allowed in tight torsos; anything else from the photo's colors).

### Combined sprites (`--pixel-art combined`)

The photo decides where pixels go and finds the graphics; Gemma decides what the colors mean
and reads any lettering. Steps 1-2 below find the color regions, then the sprite is drawn like a
template sprite: regions are tidied into flat blobs, lit from the top-left, outlined in their
darkest tone, and filled with Gemma's pattern. Near-black fabric gets lifted highlights.

Graphics (no icon library):
- **Big graphics are detected on the photo**, independent of Gemma's colors: a group of pixels
  clearly unlike the fabric (`GRAPHIC_DISTANCE`), centered in the middle of the garment, not
  running off its edge (that's a panel, hem or undershirt), spanning at least 20% of the garment's
  width or height and 1% of its area. Skipped on patterned fabric.
- **Lettering** on the biggest graphic uses Gemma's `graphic_text` with a chain sized to the fabric:
  full word (3x5 font, 2x if the print is tall enough) -> initials -> first letter, in the graphic's
  highest-contrast ink. Slogans never shrink to initials.
- **Anything else big** (or a slogan that doesn't fit) is drawn from the photo: its own shape,
  median-cut to up to 4 of its own colors.
- **Small markings are dropped**: every pixel that isn't fabric, Gemma-confirmed trim (secondary)
  or a big graphic is painted as fabric. `pixel_art.graphic_drawn` records what was drawn.

`--pixel-art hybrid --px-size 96` is the detailed alternative (step 3 below, no outline/glyph).

The photo decides where pixels go; Gemma decides what the colors mean.

1. Each pixel of the cutout is assigned to an anchor: Gemma's primary / secondary / accent colors,
   plus measured colors clearly distinct from all of them (e.g. a white outline around a print).
   Measured colors close to a chosen one are treated as its shading.
2. Each sprite pixel is a weighted majority vote over its block (6x6 cutout pixels). Accent (print)
   and trim colors vote heavier, so thin lettering survives the downsample. Rim pixels blended
   with the old background don't vote.
3. The winner is drawn with that anchor's hue-shifted ramp (shade / base / light) based on how
   much darker or lighter the photo was there, so folds and seams show up as shading.

`--pixel-art photo` is the plain alternative (Lanczos + median-cut quantize, no model needed).
Settings (`--px-size`, `--px-outline`, `--px-snap`, `--px-colors`, `--px-dither`) and the anchors
are saved in each item's `pixel_art.settings`, so results are reproducible.

## Setup

```
pip install -r requirements.txt
pip install "rembg[cpu]"           # rembg alone has no ONNX backend; first run downloads ~1 GB of models
export GEMINI_API_KEY=...          # aistudio.google.com/apikey
```

## Run

```
python -m wardrobe_pixels.generate photos/* --out out                       # Gemma 4 via API key
python -m wardrobe_pixels.generate IMG_0042.HEIC --provider ollama          # local gemma4
python -m wardrobe_pixels.generate hoodie.webp --provider test --hint hoodie  # offline fake model
uvicorn wardrobe_pixels.server:app --reload                                 # HTTP API
python -m wardrobe_pixels.showcase                                          # every template x pattern
python -m wardrobe_pixels.gallery out                                       # rebuild out/index.html
python -m pytest wardrobe_pixels/tests                                      # offline tests (pip install pytest)
```

## Using it from code

```python
from wardrobe_pixels.agent import GemmaSpriter
from wardrobe_pixels.generate import generate_item, save_item

spriter = GemmaSpriter(provider="google")          # build once
gen = await generate_item(upload_bytes, spriter)   # GeneratedItem: item dict + PIL images
save_item(gen, "out")
```

## Switching models (the plugin slot)

`GemmaSpriter(provider=..., model=..., output_mode=...)`, or env vars
`WARDROBE_PROVIDER`, `WARDROBE_MODEL`, `WARDROBE_OUTPUT_MODE` for the server.

- provider: `google` (API key), `ollama` (local), `test` (offline fake)
- output_mode: `prompted` (default, works everywhere), `tool` (function calling), `native` (schema-enforced JSON)

If Gemma returns something invalid (unknown garment, color index that doesn't exist), Pydantic AI
sends the error back and asks again, up to 3 times.

## Item format

`id, name, category, subtype, pattern, graphic, graphic_letter, graphic_text, colors {primary, secondary, accent},
palette_colors, measured_colors, warmth, formality, vibe_tags, status ("clean"|"laundry"),
sprite, sprite_large, cutout, original, worn, model, warnings, pixel_art {status ("ready"|"failed"),
sprite, preview, palette, settings, graphic_drawn}`

`out/` layout: `originals/` (uploads, byte-for-byte), `cutouts/`, `sprites/<id>.png` + `@8x` (template),
`sprites/<id>_shaped32.png` + `@8x` (shaped), `wardrobe.json`, `index.html`.
`POST /sprites` takes an optional `pixel_art` form field (`shaped` default, `combined`, `hybrid`, `photo`, `off`).

After a user edits an item, POST it to `/sprites/rerender` (or call
`render_sprite(recipe_from_item(item))`) to redraw it without calling Gemma.

## Editing templates

`templates.py`: draw the left half of symmetric items (16 chars per row). `#` fabric, `t` trim,
`d` dark detail, `l` laces/drawstrings, `.` empty. Add synonyms in `spec.py`. Check with the showcase.
