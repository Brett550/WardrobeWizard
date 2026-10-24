"""Static wardrobe grid for an output folder. Opens straight from disk, no server.

  python -m wardrobe_pixels.gallery out   -> out/index.html

Tiles show the photo-derived pixel-art sprite, falling back to the template sprite
when pixel art is missing or failed. The view switch compares against the cutout and
the original upload.
"""
from __future__ import annotations

import html
import json
import sys
from pathlib import Path

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Wardrobe</title>
<style>
  :root { --bg: #eceae6; --tile: #e3e0db; --ink: #1c1c1c; --mute: #8a8580; }
  * { box-sizing: border-box; margin: 0; }
  body { background: var(--bg); color: var(--ink);
         font: 11px/1.4 "Helvetica Neue", Helvetica, Arial, sans-serif; letter-spacing: .06em;
         text-transform: uppercase; padding: 32px clamp(16px, 4vw, 56px); }
  header { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 40px; }
  nav button { background: none; border: 0; font: inherit; letter-spacing: inherit; text-transform: inherit;
               color: var(--mute); cursor: pointer; padding: 4px 0 4px 18px; }
  nav button[aria-pressed="true"] { color: var(--ink); }
  .grid { display: grid; gap: 2px; grid-template-columns: repeat(auto-fill, minmax(min(220px, 45vw), 1fr)); }
  figure { background: var(--tile); }
  .frame { aspect-ratio: 1; display: grid; place-items: center; padding: 14%; }
  .frame img { width: 100%; height: 100%; object-fit: contain; }
  .frame img.px { image-rendering: pixelated; image-rendering: crisp-edges; }
  figcaption { padding: 10px 12px 12px; display: flex; justify-content: space-between; gap: 8px; }
  figcaption span:last-child { color: var(--mute); }
  .note { color: #a4433a; }
</style></head>
<body>
<header><div>Wardrobe — __COUNT__</div>
<nav aria-label="view"><button data-view="pixel" aria-pressed="true">Pixel</button><button data-view="template"
>Template</button><button data-view="cutout">Cutout</button><button data-view="original">Original</button></nav>
</header>
<main class="grid" id="grid"></main>
<script>
const ITEMS = __ITEMS__;
function src(it, view) {
  const px = it.pixel_art && it.pixel_art.status === "ready" ? it.pixel_art.preview : null;
  return {pixel: px || it.sprite_large, template: it.sprite_large,
          cutout: it.cutout, original: it.original || it.cutout}[view];
}
function render(view) {
  const grid = document.getElementById("grid");
  grid.replaceChildren(...ITEMS.map(it => {
    const fig = document.createElement("figure");
    const frame = Object.assign(document.createElement("div"), {className: "frame"});
    const img = Object.assign(document.createElement("img"), {src: src(it, view), alt: it.name, loading: "lazy"});
    if (view === "pixel" || view === "template") img.className = "px";
    frame.append(img);
    const cap = document.createElement("figcaption");
    const failed = view === "pixel" && !(it.pixel_art && it.pixel_art.status === "ready");
    cap.innerHTML = `<span>${esc(it.name)}</span><span${failed ? ' class="note"' : ""}>${
      failed ? "template fallback" : esc(it.subtype)}</span>`;
    fig.append(frame, cap);
    return fig;
  }));
}
function esc(s) { return String(s ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"})[c]); }
document.querySelectorAll("nav button").forEach(b => b.onclick = () => {
  document.querySelectorAll("nav button").forEach(x => x.setAttribute("aria-pressed", x === b));
  render(b.dataset.view);
});
render("pixel");
</script>
</body></html>
"""


def build(out_dir: str | Path) -> Path:
    out = Path(out_dir)
    items = json.loads((out / "wardrobe.json").read_text())
    # Embedded (not fetched) so the page works from file://. "</" is escaped so a name can't end the script.
    data = json.dumps(items).replace("</", "<\\/")
    page = PAGE.replace("__ITEMS__", data).replace("__COUNT__", html.escape(f"{len(items)} items"))
    path = out / "index.html"
    path.write_text(page)
    return path


def main():
    print(f"wrote {build(sys.argv[1] if len(sys.argv) > 1 else 'out')}")


if __name__ == "__main__":
    main()
