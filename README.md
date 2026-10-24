# 🧙 Wardrobe Wizard

**Snap your clothes, get them back as pixel art, and let Gemma 4 plan your week.**

Wardrobe Wizard turns photos of your real clothes into 32×32 pixel sprites, keeps them in a pixel closet,
and lays out a week of outfits around the weather and the vibe you're going for. Dirty clothes go in the
laundry hamper, and the planner works around them until you wash them. Drip, a pixel wizard in
sunglasses, is the app's voice: click him to ask for outfit help or to change your week by just saying
what happened ("I spilled coffee on the cocoa heart tee").

The pipeline has one rule: **Gemma 4 describes, code draws.** Gemma 4 reads images but only writes text,
so it never paints pixels. It fills in structured, validated answers, and deterministic code does the
drawing and the changing.

## The three Gemma 4 features

| Feature | What Gemma does | What code does | Endpoint |
| --- | --- | --- | --- |
| **Photo → pixel sprite** | Describes the garment: type, colors by index, pattern, printed text, and whether someone is wearing it | Cuts it out, finds big graphics, and pours the photo's regions into the hand-drawn template for that type | `POST /sprites` |
| **Drip, the wizard** | Chats, answers style questions, and calls tools (`set_slot`, `send_to_laundry`, `wash`, `replan`, `lock_day`) | Validates every tool call against the app state, then the page applies the actions | `POST /drip/chat` |
| **Week planner** | Picks seven outfits by item id from the clean closet, for the forecast and style | Rejects unknown, dirty, wrong-row or locked-day picks and repeated socks/underwear, and sends the reasons back | `POST /plan/week` |

```
 📸 photo ──► ✂️ cut out ──► 🎨 measure colors ──► 🧠 Gemma 4 ──► 📋 recipe ──► 🧩 photo regions ──► 🖼️ sprite
 (any format)   garment       from the pixels      describes it     validated     + big graphic        in template shape
```

---

## Contents

1. [What's in the box](#whats-in-the-box)
2. [Quick start](#quick-start)
3. [How the sprite pipeline works](#how-the-sprite-pipeline-works)
4. [Drip](#drip)
5. [The Gemma week planner](#the-gemma-week-planner)
6. [The front end](#the-front-end)
7. [Backend reference](#backend-reference)
8. [Timing and limits](#timing-and-limits)
9. [Customizing](#customizing)
10. [Tests](#tests)
11. [Troubleshooting](#troubleshooting)
12. [Status and roadmap](#status-and-roadmap)
13. [Credits](#credits)

---

## What's in the box

```
WizardWardrobe/
├── README.md                 ← you are here
├── DRIP_PLAN.md              ← design notes for Drip
├── wardrobe_wizard_v2.html   ← the whole front end, one file, no build step (served at / by the backend)
├── wardrobe_wizard.html      ← the earlier front end (no Drip, no Gemma planner)
├── catalog/                  ← demo closet: 40 real photos, their sprites, image-sources.csv (credits)
├── catalog_sprites_sheetReal.png ← the sheet the demo sprites were cut from
├── dripWizard.png            ← Drip's original art
└── wardrobe_pixels/          ← Python package
    ├── ingest.py             ← any image format → upright RGBA → PNG
    ├── segment.py            ← background removal (rembg or a fallback); clothing-only cut for worn photos
    ├── colors.py             ← k-means color measurement in Lab space
    ├── spec.py               ← GarmentSpec: the Pydantic model Gemma must fill in
    ├── agent.py              ← Pydantic AI harness around Gemma 4 (google / ollama / test), retries
    ├── pixelate.py           ← photo → pixel art: big-graphic detection, shaped / combined / hybrid modes
    ├── generate.py           ← the end-to-end pipeline + CLI
    ├── drip.py               ← Drip: Gemma chat agent with validated tools
    ├── planner.py            ← Gemma week planner with a plan validator
    ├── server.py             ← FastAPI: the page, sprites, Drip and the planner
    ├── render.py             ← the template renderer (palette swap, patterns, shading, prints)
    ├── templates.py          ← garment templates drawn as editable ASCII art
    ├── palette.py            ← shared palette + hue-shifted shading ramps
    ├── gallery.py            ← static wardrobe grid for a CLI output folder
    ├── demo_wardrobe.py      ← renders a 40-item template-only demo wardrobe
    ├── showcase.py           ← renders every template × pattern into one sheet
    ├── photos/               ← sample photos for the CLI smoke test
    ├── tests/                ← offline tests (no key, no network)
    ├── README.md             ← package notes: pixel-art modes, item format, template legend
    └── requirements.txt
```

---

## Quick start

### 1. Install (once)

You need **Python 3.10+** and a free API key from [Google AI Studio](https://aistudio.google.com/apikey).
Run everything from the folder that **contains** `wardrobe_pixels/`.

```bash
python3 -m venv wardrobe_pixels/.venv
wardrobe_pixels/.venv/bin/python -m pip install -r wardrobe_pixels/requirements.txt
wardrobe_pixels/.venv/bin/python -m pip install "rembg[cpu]"    # plain `rembg` has no ONNX backend
export GEMINI_API_KEY="your-key-here"
```

> If conda `(base)` is active, call the venv's python explicitly as above, or activate the venv.

### 2. Run the app (all three Gemma features)

```bash
WARDROBE_PROVIDER=google wardrobe_pixels/.venv/bin/uvicorn wardrobe_pixels.server:app --port 8000
```

Open **http://localhost:8000/**. The page detects the server through `/health`, and the pill in the top
right reads "Connected: Gemma 4 sprites + Drip". Click the closet, then:

- **Try a sample closet instead** loads the 40-item catalog closet. Click any item to see its real photo.
- **Plan week** (the wand in the tool rail) asks Gemma 4 to plan the week. It takes a minute or two.
- **Click Drip** (bottom right) to chat. Try "I spilled coffee on the cocoa heart tee".
- **Add clothes** uploads your own photos. Each becomes a pixel sprite through Gemma.

### Without a key

Open `wardrobe_wizard_v2.html` directly in a browser. In demo mode the page reads colors from your photos
in the browser and guesses each item's type (marked with **?**). Drip still answers how-to questions and
knows a few offline spells (wash everything, plan the week, lock a day, "I spilled on X"). Plan week uses
the quick local planner.

For an offline backend, use `WARDROBE_PROVIDER=test`. Fake models make real tool calls, so you can build
on the whole flow with no network.

### Just the sprite pipeline (CLI)

```bash
# offline smoke test: checks the wiring without calling Gemma
wardrobe_pixels/.venv/bin/python -m wardrobe_pixels.generate wardrobe_pixels/photos/pittSW.jpg --out out_test --provider test --hint sweatshirt
# the real thing
wardrobe_pixels/.venv/bin/python -m wardrobe_pixels.generate wardrobe_pixels/photos/pittSW.jpg --out out
open out/index.html        # wardrobe grid: Pixel / Template / Cutout / Original views
```

> **Run commands from the parent folder**, not from inside `wardrobe_pixels/`. Otherwise you'll see
> `No module named wardrobe_pixels`.

---

## How the sprite pipeline works

### 1. Ingest (`ingest.py`)

Every upload is normalized first: EXIF rotation applied, CMYK / 16-bit / palette / grayscale converted to
8-bit RGBA, animated GIF and WEBP reduced to their first frame, and anything over 1600px scaled down. HEIC
needs `pillow-heif` and SVG needs `cairosvg`. Unreadable files raise `UnsupportedImage` (HTTP 415). The
original upload is kept byte for byte.

### 2. Cut out the garment (`segment.py`)

`rembg` removes the background. Without it, a fallback separates the garment from a plain background by
color distance. If Gemma says the garment is **being worn** (`worn: true`), the photo is cut again with
rembg's clothing segmentation, keeping only the top or bottom (from Gemma's category). That keeps faces,
hands and other clothes out of the sprite. Worn shoes and hats get a warning instead.

### 3. Measure the real colors (`colors.py`)

Vision models are bad at exact hex codes, so colors are measured from the pixels: k-means in Lab space,
light and shadow of the same fabric merged, anti-aliasing fringes dropped, small but distinct prints kept.
Gemma picks colors **by index** from this list.

### 4. Ask Gemma 4 for a recipe (`agent.py` + `spec.py`)

A [Pydantic AI](https://ai.pydantic.dev/) agent sends the cutout (image first, then text) with the
numbered colors and requires a `GarmentSpec`:

```json
{
  "name": "Yellow Pitt Hoodie",
  "subtype": "hoodie",
  "pattern": "solid",
  "primary_color": 0,
  "secondary_color": 1,
  "accent_color": 1,
  "graphic": "letter",
  "graphic_letter": "P",
  "graphic_text": "PITT",
  "worn": false,
  "warmth": 4,
  "formality": 1,
  "vibe_tags": ["cozy", "collegiate"]
}
```

Before-validators quietly fix harmless variations ("Hoodie", "t-shirt", "jeans", "stripes", warmth 7) at
no retry cost. Real mistakes (unknown type, color index that doesn't exist) go back to Gemma with the
error, up to three times. Temporary API errors (500s, 429s, timeouts) are retried with backoff. Other API
errors skip that photo instead of crashing the batch.

### 5. Draw the sprite (`pixelate.py` + `render.py` + `templates.py`)

The default output (`--pixel-art shaped`) combines both approaches:

1. **Analysis (40×40).** Each pixel of the cutout is assigned to one of Gemma's colors (primary,
   secondary, accent) or a clearly distinct measured detail color.
2. **Big graphics are detected on the photo**, not from Gemma's colors: a group of pixels clearly unlike
   the fabric, centered on the garment, not running off its edge (that's a hem, panel or undershirt), at
   least 20% of the garment's width or height and 1% of its area. **Small markings are dropped** (painted
   as fabric). Patterned fabric skips detection.
3. **Shaped into the template.** The photo's garment box is mapped onto the template for Gemma's subtype.
   Each template pixel takes the photo's region there: fabric or trim (so real yellow cuffs stay yellow,
   and an open hood shows its lining). `render.py` draws the outline, shading and detail lines unchanged.
4. **Lettering** uses Gemma's `graphic_text` with a fallback chain sized to the fabric: full word (3×5
   font) → initials → first letter, in the graphic's highest-contrast ink. Slogans never shrink to
   initials. Any other big graphic is drawn from the photo's own shape and colors.

Other modes: `combined` (the photo's own silhouette, drawn in the template style), `hybrid` (a detailed
96px photo render), `photo` (plain quantize), `off` (template sprite only). Every item also gets the
classic template sprite (`sprites/<id>@8x.png`).

---

## Drip

Drip lives bottom right on the main screen. Every toast, laundry warning and weather note appears in his
speech bubble. His face follows the app: thinking while Gemma works, casting (wand out) when changes
apply, shocked when the hamper overflows or something fails, cool after planning, sleepy after a minute
idle.

| Job | Example | Needs Gemma? |
| --- | --- | --- |
| **App guide** | "How does the hamper work?" | No (canned answers) |
| **Narrator** | "You have 4 clean pairs of socks for 7 days. Do laundry by Thursday." | No |
| **Morning briefing** | "Thursday looks rainy at 46°, so Midnight Globe Tee is on it." | No |
| **Stylist** | "What should I wear Thursday?" (advice only, nothing changes) | Yes |
| **Assistant** | "I spilled coffee on the cocoa heart tee" → hamper + Monday gets a new top | Yes, with tools |

**How it's wired.** The page owns the state and sends a compact snapshot (ids, names, category, warmth,
tags, status, the plan, the forecast, the style) with the last 12 messages. Gemma's tool calls are checked
against that snapshot. A bad call ("Plain White Tee is in the hamper") goes back to Gemma as a plain
explanation, so it corrects itself. Valid calls are recorded as actions, never applied on the server. The
page applies them with its own functions (`sendToLaundry`, `wash`, `planWeek`, slot changes) and their
animations. Replies that loop on one word or run long are sent back to be rewritten.

If more than one item matches ("the hoodie" with two hoodies), Drip asks which one. Locked days are left
alone. On a server error or timeout, Drip says "My crystal ball is cloudy. Try again in a sec." and the
app keeps working.

---

## The Gemma week planner

**Plan week**, **Weather → Plan for this weather** and **Style → Plan with this style** send the clean
closet, the forecast, the style and the current plan (locked days, hat on/off) to `POST /plan/week`.
Gemma returns item ids for every unlocked day. The validator rejects:

- ids that aren't in the closet, items in the hamper, or items in the wrong row
- locked or missing days, or a hat on a "no hat" day
- empty rows when clean items exist
- repeated underwear or socks while there are enough clean pairs for every day

Problems go back to Gemma once with the reasons. On any failure (timeout, rate limit, invalid plan) the
page falls back to the quick local planner and Drip says so. Drip's own "replan" action uses the quick
planner so chat stays fast.

---

## The front end

`wardrobe_wizard_v2.html` is a single file with no build step. Served by the backend, it talks to it on
the same origin. Opened as a file, it runs in demo mode. Template sprites are drawn live by a JavaScript
port of the Python renderer, and uploads show the backend's shaped sprite.

### The flow

The page opens on a white screen with the pixel closet. Click it and the doors swing open, and a cloud
upload button rises above it. Drop photos onto the cloud (or click it), or choose **Try a sample closet
instead**. A magic wand loader runs while photos turn into pixels, then the main screen fades in with the
week planned and Drip says hi.

### The demo closet

The sample closet is the 40-item catalog from `catalog_sprites_sheetReal.png`: 8 hats, 8 tees, 8 pants,
8 socks and 8 shoes. The sprites were cut from the sheet's exact pixel grid. **Clicking an item shows its
real photo** (with the photographer and license), plus the sprite. The underwear row is hidden when the
closet has no underwear.

### Features

| Feature | How it works |
| --- | --- |
| **Drag and drop** | Drag from the closet onto a day, between days (they swap), into the hamper, or back to the closet. Wrong-row drops are refused. Works with touch. |
| **Hamper** | Fills up with the colors of what's inside. Days using a dirty item get a fresh pick. Click to see inside, drag one out to wash it, or **Wash all**. |
| **Hat or no hat** | Each day's hat slot can be "No hat". Hats default on for sunny or cold days. |
| **Lock a day** | The lock under each date protects that outfit from planning (Gemma's and local). |
| **Weather** | 7-day forecast, °F/°C, and "Plan for this weather". |
| **Style** | Vibe (comfy, campus, sporty, dressed up) and color mood (calm, mixed, bold). |
| **Filter and Sort** | By type, optionally including the hamper. Sort by recent, type, color, warmth, most planned or name. |
| **Item details** | Real photo, rename, change type or main color (the sprite redraws), plan it for a day, or send it to the hamper. |
| **Accessibility** | Visible keyboard focus, labelled controls, dialogs, reduced-motion support, dark mode, a layout that stacks on narrow screens, live regions for Drip. |

---

## Backend reference

### HTTP API (`server.py`)

| Endpoint | Body | Returns |
| --- | --- | --- |
| `GET /` | | The front end (`wardrobe_wizard_v2.html`, or `WARDROBE_PAGE`) |
| `GET /health` | | `{ok, provider, model}`; the page uses it to leave demo mode |
| `GET /catalog/...` | | Demo closet photos |
| `POST /sprites` | multipart: `file`, optional `hint`, optional `pixel_art` (`shaped` default, `combined`, `hybrid`, `photo`, `off`) | Item JSON, `sprite_png`, `sprite_large_png`, `cutout_png` and `pixel_art.{sprite_png, preview_png, graphic_drawn, settings}` |
| `POST /sprites/rerender` | An edited item JSON | Fresh template sprites, no Gemma call |
| `POST /drip/chat` | `{messages, wardrobe, plan, forecast, style, today}` | `{message, mood, actions}` |
| `POST /plan/week` | `{wardrobe, plan, forecast, style, days?}` | `{days: [{day, hat, top, bottom, underwear, socks, shoes}]}` |

Errors: **415** unreadable image, **413** upload over 20 MB, **422** bad request body, **502** Gemma
failed (the message says why: no valid answer, rate limit, API error).

### CLI

```bash
wardrobe_pixels/.venv/bin/python -m wardrobe_pixels.generate PHOTOS... [options]
```

| Option | Default | Description |
| --- | --- | --- |
| `--out DIR` | `out` | Where sprites, cutouts, originals, `wardrobe.json` and `index.html` go |
| `--provider` | `google` | `google` (API key), `ollama` (local), or `test` (offline fake) |
| `--model ID` | `gemma-4-26b-a4b-it` | Any Gemma 4 id from AI Studio |
| `--output-mode` | `prompted` | `prompted`, `tool` or `native` for the sprite spec |
| `--hint TYPE` | none | Nudges the type, e.g. `--hint hoodie` |
| `--no-snap` | off | Template sprite keeps exact photo colors instead of the shared palette |
| `--concurrency N` | `2` | Parallel photos; use `1` on the free tier |
| `--pixel-art` | `shaped` | `shaped`, `combined`, `hybrid`, `photo` or `off` |
| `--px-size N` | `40` | Analysis resolution (shaped/combined), sprite size (hybrid: try 96) |
| `--px-outline`, `--px-snap`, `--px-colors`, `--px-dither` | | Fine-tuning for the other modes |

Output per item: `originals/<id>.<ext>`, `cutouts/<id>.png`, `sprites/<id>.png` and `@8x` (template),
`sprites/<id>_shaped32.png` and `@8x` (shaped), plus an entry in `wardrobe.json`. The id is a hash of the
photo, so re-running a photo updates its entry.

### Environment variables

| Variable | Used by | Purpose |
| --- | --- | --- |
| `GEMINI_API_KEY` | `google` provider | Your Google AI Studio key (`GOOGLE_API_KEY` also works) |
| `WARDROBE_PROVIDER` | server | `google`, `ollama`, or `test` |
| `WARDROBE_MODEL` | server | Overrides the model id |
| `WARDROBE_OUTPUT_MODE` | server | Sprite spec output: `prompted`, `tool`, or `native` |
| `WARDROBE_PLAN_OUTPUT` | server | Planner output: `prompted` (default) or `tool` |
| `WARDROBE_PAGE` | server | Path of the HTML served at `/` |
| `OLLAMA_BASE_URL` | `ollama` provider | Defaults to `http://localhost:11434/v1` |

Never commit your key. Keep it in your shell or a `.env` file listed in `.gitignore`.

### Using it from Python

```python
from wardrobe_pixels.agent import GemmaSpriter
from wardrobe_pixels.generate import generate_item, save_item
from wardrobe_pixels.pixelate import PixelArtOptions

spriter = GemmaSpriter(provider="google")                          # build once, reuse
gen = await generate_item(upload_bytes, spriter, pixel_art=PixelArtOptions())   # shaped sprite
item = save_item(gen, "out")
```

---

## Timing and limits

Measured on a laptop CPU with the free AI Studio tier:

| Step | Typical time | Why |
| --- | --- | --- |
| Drip reply | 3–6 s | One short Gemma call, plus one per tool round |
| Gemma week planner | 1–2.5 min | Gemma 4 thinks (~6–7k tokens) before answering, and AI Studio doesn't support `thinking_budget` / `thinking_level` for it |
| Photo upload | up to ~2 min per photo | Background removal runs on CPU. The first run also downloads ~1 GB of rembg models to `~/.rembg`, and worn photos get a second clothing-only pass |

- **Rate limits.** The free tier allows only a few requests per minute. A 429 shows as "Gemma is out of
  spells for a minute". Wait and try again.
- **Google 500s.** AI Studio sometimes returns `500 Internal error`. Each call retries automatically. If a
  photo still fails, rerun it alone with `--concurrency 1`.
- **Gemma loops.** Gemma 4 occasionally repeats one word in free text. Drip's replies are checked and sent
  back, and the planner returns ids only for this reason.

---

## Customizing

**Add or edit a garment template.** Open `templates.py`. Symmetric items are drawn as the left half and
mirrored; shoes and socks are drawn full width. Add synonyms in `spec.py` so Gemma's wording maps onto it,
check with `python -m wardrobe_pixels.showcase`, and mirror the template in the `TPL` object in the HTML.

**Tune graphic detection.** `GRAPHIC_DISTANCE`, `BIG_GRAPHIC_SPAN` and `BIG_GRAPHIC_AREA` at the top of
the graphics section in `pixelate.py` decide what counts as a big graphic.

**Change Drip's personality.** `PERSONA` in `drip.py`. The canned app guide is `GUIDE` in the HTML.

**Change how Gemma plans.** `PLANNER` in `planner.py` (the rules), and `problems()` (the hard checks).

**Swap the demo closet.** The `SAMPLE` array in the HTML: id, name, subtype, warmth, formality, tags,
sprite (data URL), photo path and credit.

**Re-theme every sprite.** Swap the palette in `palette.py` (and `PAL` in the HTML).

**Real weather.** Replace `getForecast()` in the HTML with a weather API that returns
`{ cond, hi, lo }` per day (`cond`: `sun`, `partly`, `cloud` or `rain`).

---

## Tests

```bash
wardrobe_pixels/.venv/bin/python -m pip install pytest
wardrobe_pixels/.venv/bin/python -m pytest wardrobe_pixels/tests
```

66 offline tests, no key or network: sprite sizing, transparency, proportions and determinism; big-graphic
detection and dropping of small markings; the text fallback chain; template-shaped sprites; Drip's tool
validation (dirty items, wrong rows, locked days, unknown ids, ambiguity, looping replies); the planner
validator; and every endpoint with the offline models.

---

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `No module named wardrobe_pixels` | You're inside the package folder. `cd ..` and try again. |
| `No onnxruntime backend found` | `pip install "rembg[cpu]"` |
| `API key not valid` | Make a new key at AI Studio, `export GEMINI_API_KEY=...`, and restart the server. |
| Pill says "Demo mode" | Open the page from the server (`http://localhost:8000/`) or add `?api=http://localhost:8000`. |
| Drip: "crystal ball is cloudy" | The server is down or Gemma failed. Check the uvicorn log; the 502 message says why. |
| "Gemma is out of spells for a minute" | Free-tier rate limit (429). Wait a minute. |
| Plan week takes a long time | Normal: Gemma thinks for 1–2.5 minutes. The wand wiggles while it works. |
| Upload takes a long time | Normal on CPU, especially the first run (model download) and worn photos. |
| Model not found (404) | Copy the exact Gemma 4 id from AI Studio and set `WARDROBE_MODEL` / `--model`. |
| Background left in the cutout | Install `rembg[cpu]`, or shoot on a plain background that contrasts with the clothing. |
| HEIC won't load | `pip install pillow-heif` for the backend. In demo mode use JPG or PNG. |

---

## Status and roadmap

**Working and tested against live Gemma 4:** photo → shaped sprite (including worn photos and printed
lettering), Drip chat with tools, the Gemma week planner, and the full front-end flow on the catalog demo
closet. The offline test suite covers the validators and endpoints.

**Known limits:**

- Uploads are slow on CPU, and the server handles one heavy upload at a time.
- Gemma planning takes minutes because thinking can't be limited on AI Studio's Gemma 4.
- Patterned fabric skips graphic detection, so a big logo on a striped shirt isn't found.
- Worn shoes and hats have no clothing-only cut.
- Edited uploads are redrawn in the browser from the template, not from the photo.
- No dress template.
- Decisions live in the page and reset on reload.

**Next up:**

- Saving the wardrobe between sessions
- Faster uploads (a smaller rembg model, or a background job queue)
- An optional `--productize` step that turns worn-clothing photos into clean product shots
- A real weather API
- Wear tracking, so items move to the hamper after a planned day passes

---

## Credits

Built at a mini hackathon by the Wardrobe Wizard team. Pixel palette based on
[ENDESGA 32](https://lospec.com/palette-list/endesga-32). Garment recognition, Drip and the planner by
[Gemma 4](https://ai.google.dev/gemma), orchestrated with [Pydantic AI](https://ai.pydantic.dev/).
Demo closet photos are from [Wikimedia Commons](https://commons.wikimedia.org/) under their own licenses
(public domain, CC0, CC BY and CC BY-SA). Each photo's creator, license and source page are listed in
`catalog/image-sources.csv` and shown in the app's item details.
