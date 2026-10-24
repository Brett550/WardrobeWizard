# 🧙 Wardrobe Wizard

**Snap your clothes, get them back as pixel art, and let Gemma 4 plan your week.**

Wardrobe Wizard turns photos of your real clothes into cute 32×32 pixel sprites. It keeps them in a little
pixel closet and lays out a week of outfits around the weather and the vibe you're going for. Dirty
clothes go in the laundry hamper, and the planner works around them until you wash them.

It was built for a mini hackathon. The pipeline has one rule: **Gemma 4 describes, code draws.**
Gemma 4 can read images but only writes text, so it never tries to paint pixels. It fills in a structured
recipe, and a deterministic renderer turns that recipe into a sprite. That keeps every item on-style,
fast, and cheap.

```
 📸 photo ──► ✂️ cut out ──► 🎨 measure colors ──► 🧠 Gemma 4 ──► 📋 recipe ──► 🖼️ pixel sprite
 (any format)   garment       from the pixels      describes it     validated     drawn from
                                                   as JSON          by Pydantic   templates
```

---

## Contents

1. [What's in the box](#whats-in-the-box)
2. [Quick start](#quick-start)
3. [How the sprite pipeline works](#how-the-sprite-pipeline-works)
4. [The front end](#the-front-end)
5. [Backend reference](#backend-reference)
6. [Customizing](#customizing)
7. [Running it with Claude Code](#running-it-with-claude-code)
8. [Troubleshooting](#troubleshooting)
9. [Status and roadmap](#status-and-roadmap)
10. [Credits](#credits)

---

## What's in the box

```
wardrobe-wizard/
├── README.md                 ← you are here
├── CLAUDE.md                 ← drop-in instructions for Claude Code
├── wardrobe_wizard.html      ← the whole front end, one file, no build step
├── assets/                   ← standalone hamper / basket sprites + their generator scripts
└── wardrobe_pixels/          ← Python package: photo → sprite pipeline
    ├── ingest.py             ← any image format → upright RGBA → PNG
    ├── segment.py            ← background removal (rembg, or a plain-background fallback)
    ├── colors.py             ← k-means color measurement in Lab space
    ├── spec.py               ← GarmentSpec: the Pydantic model Gemma must fill in
    ├── agent.py              ← Pydantic AI harness around Gemma 4 (google / ollama / test)
    ├── generate.py           ← the end-to-end pipeline + CLI
    ├── server.py             ← FastAPI endpoints for the front end
    ├── render.py             ← the sprite renderer (palette swap, patterns, shading, prints)
    ├── templates.py          ← garment templates drawn as editable ASCII art
    ├── palette.py            ← shared palette + hue-shifted shading ramps
    ├── showcase.py           ← renders every template × pattern into one sheet
    └── requirements.txt
```

| Piece | What it does |
| --- | --- |
| **Sprite pipeline** | Accepts JPG, PNG, WEBP, HEIC, GIF, BMP, TIFF and SVG. It removes the background, measures the real fabric colors, asks Gemma 4 for a recipe, and renders a 32×32 sprite plus an 8× version. |
| **Garment templates** | Tees, long sleeves, hoodies, pants, shorts, sneakers and caps in Python. The front end adds underwear and socks. |
| **Patterns and prints** | Solid, striped, vertical stripes, plaid, checkered, polka dot, floral, camo and denim. Prints include stars, hearts, circles, box logos, "text", and single letters or numbers in a 3×5 pixel font. |
| **Week planner** | Fills Monday to Sunday with hat, top, bottom, underwear, socks and shoes. It weighs the forecast, your chosen style, color mood and variety. |
| **Laundry hamper** | Drag clothes in and the basket fills up with their colors. Those items leave the plan and get replaced until you wash them. |
| **Tool rail** | Weather, Style, Plan week, Filter, Sort and Add clothes. |

---

## Quick start

### Just the front end (30 seconds, no setup)

Open `wardrobe_wizard.html` in a browser. Click the closet, then either upload a few photos or choose
**Try a sample closet instead**. In this demo mode, the page reads colors from your photos in the browser
and guesses each item's type, marked with a **?** you can tap to correct.

### The real pipeline (Gemma 4 via your Google AI Studio key)

You need **Python 3.10+** and a free API key from [Google AI Studio](https://aistudio.google.com/apikey).

```bash
# from the folder that CONTAINS wardrobe_pixels/
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r wardrobe_pixels/requirements.txt
pip install rembg                    # optional, much better cutouts on messy backgrounds

export GEMINI_API_KEY="your-key-here"

# 1. offline smoke test: checks the wiring without calling Gemma
python -m wardrobe_pixels.generate wardrobe_pixels/photos/pittSW.jpg --provider test --hint sweatshirt

# 2. the real thing
python -m wardrobe_pixels.generate wardrobe_pixels/photos/pittSW.jpg --out out
open out/sprites/                    # macOS; look for the @8x.png
```

> **Run commands from the parent folder**, not from inside `wardrobe_pixels/`. Otherwise Python can't
> find the package, and you'll see `No module named wardrobe_pixels`.

### Front end + backend together

```bash
pip install fastapi uvicorn python-multipart
export GEMINI_API_KEY="your-key-here"
export WARDROBE_PROVIDER=google
uvicorn wardrobe_pixels.server:app --reload --port 8000
```

Then open the front end with the API address in the URL:

```
wardrobe_wizard.html?api=http://localhost:8000
```

The pill in the top-right corner switches from "Demo mode" to "Connected to sprite server." Uploads now go
through Gemma, and the guess markers disappear.

---

## How the sprite pipeline works

### 1. Ingest (`ingest.py`)

Every upload is normalized before anything else touches it. EXIF rotation is applied, because phone
photos are often stored sideways. CMYK, 16-bit, palette and grayscale images are converted to 8-bit RGBA.
Animated GIFs and WEBPs use their first frame, and anything larger than 1600px is scaled down. HEIC needs
`pillow-heif` and SVG needs `cairosvg`. Unreadable files raise a clear `UnsupportedImage` error, which
the server turns into a 415 response.

### 2. Cut out the garment (`segment.py`)

When `rembg` is installed, it handles background removal and works on real-world photos. Without it, a
fallback estimates the background color from the image border and separates the garment by color
distance. It keeps striped garments in one piece and refuses to fill concave gaps like armpits with
background. The fallback works best on a plain bed, floor or wall that contrasts with the clothing.

### 3. Measure the real colors (`colors.py`)

Vision-language models are bad at exact hex codes, so colors are measured from the pixels instead. A
k-means pass runs in Lab color space. Clusters that are the same fabric in light and shadow are merged,
and the pink fringe where red and white stripes meet is dropped. A small chest logo is kept, because it
is tiny but very different from the fabric. Gemma then picks colors **by index** from this list, never by
inventing hex values.

### 4. Ask Gemma 4 for a recipe (`agent.py` + `spec.py`)

A [Pydantic AI](https://ai.pydantic.dev/) `Agent` sends the cleaned PNG (image first, then text) along
with the numbered color list. It requires a `GarmentSpec` back:

```json
{
  "name": "Pitt Script Crewneck",
  "subtype": "longsleeve",
  "pattern": "solid",
  "primary_color": 0,
  "secondary_color": null,
  "accent_color": 1,
  "graphic": "letter",
  "graphic_letter": "P",
  "warmth": 4,
  "formality": 1,
  "vibe_tags": ["cozy", "collegiate"]
}
```

Validation works in two layers. **Before-validators quietly fix harmless variations**: "Hoodie" becomes
`hoodie`, "t-shirt" becomes `tshirt`, "jeans" becomes `pants`, "stripes" becomes `striped`, and a warmth
of 7 is clamped to 5. None of these cost a retry. **Real mistakes fail validation and go back to Gemma**
with the error message, up to three times. That covers an unknown garment type and a color index that
doesn't exist, which an output validator checks against the measured colors.

### 5. Render the sprite (`render.py` + `templates.py` + `palette.py`)

Each garment type is an ASCII template, and the renderer fills it in:

```
 .  transparent      #  main fabric (primary color + pattern)      t  trim (collar, cuffs, soles, brim)
 d  dark detail line (pockets, seams, hood)                         l  laces / drawstrings
```

Outlines are added automatically one pixel outside the silhouette. Light comes from the top left, so
right and bottom edges are shaded and top and left edges highlighted. Shadows shift slightly cooler and
highlights slightly warmer, which is what makes it read as pixel art rather than a dimmed photo. Every
color snaps to one shared palette ([ENDESGA 32](https://lospec.com/palette-list/endesga-32) plus
clothing-friendly olives, khakis, greys, navy and maroon), so a closet full of very different photos
still looks like one game. Denim and camo noise is seeded by the item ID, so two pairs of jeans never
look identical.

---

## The front end

`wardrobe_wizard.html` is a single file with no build step and no dependencies. Its sprites are drawn
live by a JavaScript port of the Python renderer, using the same templates and palette, so items look
identical whether they came from the backend or the browser.

### The flow

The page opens on a white screen with the pixel closet in the middle. Click it and the doors swing open
to show the clothes inside, and a cloud upload button rises above it. Drop photos onto the cloud (or
click it to choose files). They fly in, the cloud squishes and poofs twice, and a magic wand loader counts
through the photos. Then the main screen fades in with your week already planned.

### The main screen

```
┌────────────────────────────────────────────────────────────────────────────────────┐
│ WARDROBE WIZARD   Week of Oct 19                                    [ demo mode ]  │
├──────────────┬──────────────────────────────────────────────────────────┬──────────┤
│ Closet       │        Mon   Tue   Wed   Thu   Fri   Sat   Sun          │ Weather  │
│ ┌──┐┌──┐┌──┐ │        ☀64°  ⛅58°  ☁51°  🌧46°  ⛅55°  ☀67°  ☁60°     │ Style    │
│ └──┘└──┘└──┘ │ Hat    [🧢]  no hat  …                                   │ Plan week│
│ ┌──┐┌──┐┌──┐ │ Top    [👕]  [🧥]   …                                    │ Filter   │
│ └──┘└──┘└──┘ │ Bottom [👖]  …                                           │ Sort     │
│              │ Undies …                                                 │ Add      │
│ Hamper 🧺 3  │ Socks  …                                                 │ clothes  │
│ [Wash all]   │ Shoes  …                                                 │          │
│              │ "You have 4 clean pairs of underwear. Do laundry by Thu." │          │
└──────────────┴──────────────────────────────────────────────────────────┴──────────┘
```

| Feature | How it works |
| --- | --- |
| **Drag and drop** | Drag from the closet onto any day, between days (the two items swap), into the hamper, or back to the closet to clear a slot. Wrong-row drops are refused with a message. It's pointer-based, so it also works with touch. |
| **Hamper** | It fills in four stages using the colors of what's inside. Any day using a dirty item gets a fresh pick. Click the basket to see what's in it, drag one item out to wash just that, or press **Wash all**. |
| **Hat or no hat** | Each day's hat slot can be switched to "No hat." Hats default on for sunny or cold days. |
| **Lock a day** | The lock under each date protects that outfit from **Plan week**. |
| **Weather** | 7-day forecast with °F/°C, plus "Plan for this weather." Cold days push the planner toward warmer layers, and hot days allow shorts. |
| **Style** | Pick a vibe (comfy, campus, sporty, dressed up) and a color mood (calm, mixed, bold), then re-plan. |
| **Filter and Sort** | Filter the closet by clothing type and optionally show items in the hamper. Sort by recently added, type, color, warmth, most planned or name. |
| **Item details** | Click any item to rename it, change its type or main color (the sprite redraws instantly), plan it for a day, or send it to the hamper. Everything here works by keyboard too. |
| **Laundry warnings** | For example, "You have 4 clean pairs of underwear for 7 days. Do laundry by Thursday." It also warns when a cold day has a light top. |
| **Accessibility** | Visible keyboard focus, labelled controls, dialogs for details, respect for reduced-motion settings, dark mode, and a layout that stacks on narrow screens. |

### How the planner scores clothes

For each unlocked day and category, every clean item gets a score. Points come from how close its warmth
is to what the temperature calls for, how many of its tags match your chosen style, and whether its color
fits your color mood. It loses points for each time it's already planned that week, and heavily for
repeated underwear and socks. A little randomness keeps weeks from looking identical. The best-scoring
item wins.

---

## Backend reference

### CLI

```bash
python -m wardrobe_pixels.generate PHOTOS... [options]
```

| Option | Default | Description |
| --- | --- | --- |
| `--out DIR` | `out` | Where sprites, cutouts and `wardrobe.json` go |
| `--provider` | `google` | `google` (API key), `ollama` (local), or `test` (offline fake) |
| `--model ID` | `gemma-4-26b-a4b-it` | Any Gemma 4 ID from AI Studio; `gemma-4-31b-it` is the larger option |
| `--output-mode` | `prompted` | `prompted` works everywhere; `tool` uses function calling; `native` uses schema-enforced JSON |
| `--hint TYPE` | none | Nudges the type, e.g. `--hint hoodie` |
| `--no-snap` | off | Keep exact photo colors instead of the shared palette |
| `--concurrency N` | `2` | Parallel uploads; keep it low on the free tier |

Output for each item: `out/sprites/<id>.png` (32px), `out/sprites/<id>@8x.png`, `out/cutouts/<id>.png`,
and an entry in `out/wardrobe.json`. The ID is a hash of the photo, so re-running the same photo updates
its entry instead of duplicating it.

### Environment variables

| Variable | Used by | Purpose |
| --- | --- | --- |
| `GEMINI_API_KEY` | `google` provider | Your Google AI Studio key. `GOOGLE_API_KEY` also works. |
| `WARDROBE_PROVIDER` | server | `google`, `ollama`, or `test` |
| `WARDROBE_MODEL` | server | Overrides the model ID |
| `WARDROBE_OUTPUT_MODE` | server | `prompted`, `tool`, or `native` |
| `OLLAMA_BASE_URL` | `ollama` provider | Defaults to `http://localhost:11434/v1` |

Never commit your key. Keep it in your shell or a `.env` file listed in `.gitignore`.

### HTTP API (`server.py`)

| Endpoint | Body | Returns |
| --- | --- | --- |
| `POST /sprites` | multipart: `file` (any image), optional `hint` | The item JSON plus `sprite_png`, `sprite_large_png` and `cutout_png` as base64 data URLs |
| `POST /sprites/rerender` | An edited item JSON | Fresh `sprite_png` and `sprite_large_png`, with no Gemma call |

Errors: **415** for an image that can't be read, **502** when Gemma never produced a valid spec.

### Using it from Python

```python
from wardrobe_pixels.agent import GemmaSpriter
from wardrobe_pixels.generate import generate_item, save_item, recipe_from_item
from wardrobe_pixels.render import render_sprite

spriter = GemmaSpriter(provider="google")          # build once, reuse for every upload
gen = await generate_item(upload_bytes, spriter)   # → item dict + PIL images
item = save_item(gen, "out")

item["colors"]["primary"] = "#e43b44"               # user fixed a color in the UI
render_sprite(recipe_from_item(item), scale=8).save("fixed.png")
```

### The item record

```json
{
  "id": "3f9a1c02be",
  "name": "Cozy Navy Hoodie",
  "category": "top",
  "subtype": "hoodie",
  "pattern": "solid",
  "graphic": "letter",
  "graphic_letter": "P",
  "colors": { "primary": "#25346d", "secondary": null, "accent": "#ecedef" },
  "palette_colors": { "primary": "#1f2a52", "secondary": null, "accent": "#dcdcdc" },
  "measured_colors": [{ "hex": "#25346d", "share": 0.99 }, { "hex": "#ecedef", "share": 0.01 }],
  "warmth": 4,
  "formality": 1,
  "vibe_tags": ["cozy", "collegiate"],
  "status": "clean",
  "sprite": "sprites/3f9a1c02be.png",
  "sprite_large": "sprites/3f9a1c02be@8x.png",
  "cutout": "cutouts/3f9a1c02be.png",
  "model": "google:gemma-4-26b-a4b-it",
  "warnings": []
}
```

`status` is the hook for the laundry hamper: `"clean"` or `"laundry"`. `warmth` and `formality` feed the
planner.

---

## Customizing

**Add or edit a garment template.** Open `templates.py`. Symmetric items are drawn as the left half
(16 characters per row) and mirrored automatically. Shoes and socks are drawn full width. Add the new
name to `SUBTYPE_SYNONYMS` in `spec.py` so Gemma's wording maps onto it. Then run
`python -m wardrobe_pixels.showcase` to see it in every pattern. Mirror the change in the `TPL` object
in `wardrobe_wizard.html` so the front end draws it too.

**Re-theme every sprite.** Swap the palette list in `palette.py` (and `PAL` in the HTML). Every sprite in
the app re-colors at once.

**Real weather.** Replace `getForecast()` in `wardrobe_wizard.html` with a call to any weather API. It
just needs to return `{ cond, hi, lo }` for each of the seven days, with `cond` set to `sun`, `partly`,
`cloud` or `rain`.

**Planner behavior.** All the weights live in `scoreItem()` in the HTML. For a smarter planner, send
the clean wardrobe JSON plus the forecast to Gemma and ask for seven outfits by item ID. The same
Pydantic AI pattern used for sprites (a schema, plus a validator that rejects unknown or dirty IDs)
applies directly.

---

## Running it with Claude Code

`CLAUDE.md` is a drop-in task file. Put it next to the `wardrobe_pixels/` folder, then run:

```bash
cd path/to/wardrobe-wizard
export GEMINI_API_KEY="your-key-here"   # set before launching, so Claude Code inherits it
claude
```

Then tell it: **"Follow CLAUDE.md and get pittSW.jpg running."** It reuses your virtual environment,
installs dependencies, runs the offline test first, then the real Gemma run, and checks the resulting
sprite. It's instructed never to print or save your key, and to make small targeted fixes rather than
rewrite the renderer.

---

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `No module named wardrobe_pixels` | You're inside the package folder. Run `cd ..` and try again. |
| `Set GEMINI_API_KEY` | Run `export GEMINI_API_KEY="..."` in the same terminal. Check it with `echo $GEMINI_API_KEY`. |
| Model not found (404) | Copy the exact Gemma 4 ID from AI Studio and pass `--model <id>`. |
| Gemma rejects JSON or tool mode | Stay on `--output-mode prompted` (the default). |
| "Gemma never produced a valid spec" | The validation errors are in the message. Add a synonym in `spec.py`, or use `--hint`. |
| Background left in the cutout | `pip install rembg`, or shoot on a plain background that contrasts with the clothing. |
| HEIC won't load | `pip install pillow-heif` for the backend. In the browser, HEIC only previews in Safari, so use JPG or PNG in demo mode. |
| 429 / rate limited | Wait a minute and use `--concurrency 1`. |
| Front end still says "Demo mode" | Open it with `?api=http://localhost:8000` and make sure `uvicorn` is running. |

---

## Status and roadmap

**Working and tested:** image ingestion across formats, background removal, color measurement, the sprite
renderer, and the full front-end flow (intro, uploads, drag and drop, hamper, planner and all tool panels).

**Written but not yet run against the live API:** the Pydantic AI harness in `agent.py`. It was written
against the current Pydantic AI docs, and the `--provider test` smoke test is the first thing to run.

**Next up:**

- Gemma-powered outfit planning, replacing the local scoring
- Saving the wardrobe between sessions (a database or file on the backend)
- Underwear and socks templates in the Python renderer, to match the front end
- An optional `--productize` step that turns photos of worn clothing into clean product shots before
  segmentation
- A real weather API
- Wear tracking, so items move to the hamper automatically after a planned day passes

---

## Credits

Built at a mini hackathon by the Wardrobe Wizard team. Pixel palette based on
[ENDESGA 32](https://lospec.com/palette-list/endesga-32). Garment recognition by
[Gemma 4](https://ai.google.dev/gemma), orchestrated with [Pydantic AI](https://ai.pydantic.dev/).
All sprites, templates and UI art are original.
