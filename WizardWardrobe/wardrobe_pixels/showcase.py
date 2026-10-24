"""Render every template x pattern into one sheet. Rerun after editing templates.

  python -m wardrobe_pixels.showcase  -> showcase.png
"""
from PIL import Image

from .render import PATTERNS, SpriteRecipe, render_sprite
from .templates import SUBTYPES

SCALE = 4
CELL = 32 * SCALE


def main(path: str = "showcase.png"):
    sheet = Image.new("RGBA", (CELL * len(PATTERNS), CELL * len(SUBTYPES)), (244, 236, 220, 255))
    colors = [("#3b5dc9", "#f4f4f4"), ("#e43b44", "#fee761"), ("#4b5a2a", "#d9c9a3"),
              ("#2b3f63", "#4a6a9c"), ("#b55088", "#ffffff"), ("#1e1e1e", "#e43b44"),
              ("#feae34", "#733e39"), ("#63c74d", "#193c3e"), ("#c0cbdc", "#3a4466")]
    for row, sub in enumerate(SUBTYPES):
        for col, pat in enumerate(PATTERNS):
            p, s = colors[(row + col) % len(colors)]
            graphic = "letter" if pat == "solid" else "none"
            sprite = render_sprite(SpriteRecipe(sub, p, s, pattern=pat, graphic=graphic,
                                                graphic_letter="P", seed=f"{sub}{pat}"), SCALE)
            sheet.alpha_composite(sprite, (col * CELL, row * CELL))
    sheet.save(path)
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
