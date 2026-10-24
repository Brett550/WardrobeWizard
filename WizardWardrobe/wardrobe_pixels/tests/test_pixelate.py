"""Offline tests: synthetic images, provider "test", no network or rembg model needed.

  python -m pytest wardrobe_pixels/tests      (from the folder that contains wardrobe_pixels/)
"""
import asyncio
import io
import json

import numpy as np
import pytest
from PIL import Image

from wardrobe_pixels.agent import GemmaSpriter
from wardrobe_pixels.gallery import build as build_gallery
from wardrobe_pixels.generate import generate_item, save_item
from wardrobe_pixels.ingest import UnsupportedImage, load_image
from wardrobe_pixels.palette import ramp
from wardrobe_pixels.render import SpriteRecipe
from wardrobe_pixels.pixelate import (WORK_FACTOR, Anchor, PixelArtOptions, anchors_from_spec,
                                      generate_pixel_art, normalize_and_center, render_hybrid)
from wardrobe_pixels.segment import cut_out_worn_garment

YELLOW, NAVY = (225, 189, 48), (17, 26, 64)
ANCHORS = [Anchor("#e1bd30", "primary"), Anchor("#111a40", "accent")]
RECIPE = SpriteRecipe("hoodie", "#e1bd30", accent="#111a40", graphic="logo", seed="t")
MODES = ["combined", "hybrid", "photo"]


def garment(w=300, h=200, color=YELLOW, canvas=(400, 400)):
    """Opaque rectangle on a transparent canvas, with a navy chest print."""
    img = Image.new("RGBA", canvas, (0, 0, 0, 0))
    body = Image.new("RGBA", (w, h), (*color, 255))
    body.paste((*NAVY, 255), (w // 3, h // 4, w // 3 + w // 4, h // 4 + h // 8))
    img.paste(body, ((canvas[0] - w) // 2, (canvas[1] - h) // 2))
    return img


def bbox_ratio(sprite):
    x0, y0, x1, y1 = Image.fromarray(np.asarray(sprite)[..., 3]).getbbox()
    return (x1 - x0) / (y1 - y0)


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("size", [40, 96])
def test_size_transparency_and_palette(mode, size):
    opts = PixelArtOptions(mode=mode, sprite_size=size, preview_size=size * 8)
    r = generate_pixel_art(garment(), opts, ANCHORS, RECIPE)
    sprite, preview = np.asarray(r["sprite"]), np.asarray(r["preview"])
    assert sprite.shape == (size, size, 4) and preview.shape == (size * 8, size * 8, 4)
    assert set(np.unique(sprite[..., 3])) <= {0, 255}                     # hard edges only
    assert sprite[0, 0, 3] == sprite[-1, -1, 3] == 0                      # transparent margin
    assert len(r["palette"]) <= opts.palette_colors
    # Nearest-neighbor preview: every 8x8 block is one flat color.
    blocks = preview.reshape(size, 8, size, 8, 4)
    assert (blocks == blocks[:, :1, :, :1]).all()


@pytest.mark.parametrize("mode", MODES)
def test_proportions_preserved(mode):
    for w, h in ((300, 100), (100, 300)):
        r = generate_pixel_art(garment(w, h), PixelArtOptions(mode=mode, sprite_size=96, preview_size=768),
                               ANCHORS, RECIPE)
        assert bbox_ratio(r["sprite"]) == pytest.approx(w / h, rel=0.1)


def test_padding_is_proportional():
    sq = normalize_and_center(garment(300, 150), PixelArtOptions(padding_fraction=0.10))
    assert sq.width == sq.height == round(300 / 0.8)


@pytest.mark.parametrize("mode", MODES)
def test_deterministic(mode):
    a = generate_pixel_art(garment(), PixelArtOptions(mode=mode), ANCHORS, RECIPE)
    b = generate_pixel_art(garment(), PixelArtOptions(mode=mode), ANCHORS, RECIPE)
    assert a["sprite"].tobytes() == b["sprite"].tobytes()


def test_hybrid_uses_only_anchor_ramps():
    r = generate_pixel_art(garment(), PixelArtOptions(mode="hybrid", outline=True), ANCHORS)
    allowed = {c for a in ANCHORS for c in ramp(a.hex, False).values()}
    assert set(r["palette"]) <= allowed


def test_accent_weight_protects_thin_print():
    """A print covering 1/3 of a sprite pixel loses a plain majority vote but survives as an accent."""
    n, k = 32, WORK_FACTOR
    sq = Image.new("RGBA", (n * k, n * k), (*YELLOW, 255))
    stripe_x = 10 * k
    sq.paste((*NAVY, 255), (stripe_x, 0, stripe_x + k // 3, n * k))     # 2 of 6 hi-res columns
    opts = PixelArtOptions(mode="hybrid", sprite_size=n, preview_size=n * 8, min_speck=1)

    def has_stripe(role):
        sprite, _ = render_hybrid(sq, [Anchor("#e1bd30", "primary"), Anchor("#111a40", role)], opts)
        col = np.asarray(sprite)[4:-4, 10, :3]
        return (np.abs(col.astype(int) - NAVY).sum(-1) < 120).mean() > 0.9

    assert has_stripe("accent")
    assert not has_stripe("primary")


def test_anchors_merge_shading_and_keep_distinct_details():
    measured = [{"hex": "#e1bd30", "share": 0.8}, {"hex": "#c9a62a", "share": 0.1},   # shadow of yellow
                {"hex": "#111a40", "share": 0.08}, {"hex": "#f2f2f2", "share": 0.02}]  # print + outline
    anchors = anchors_from_spec({"primary": "#e1bd30", "secondary": None, "accent": "#111a40"}, measured)
    assert [(a.hex, a.role) for a in anchors] == [
        ("#e1bd30", "primary"), ("#111a40", "accent"), ("#f2f2f2", "detail")]


def test_failures_raise_clearly():
    with pytest.raises(ValueError):
        generate_pixel_art(Image.new("RGBA", (50, 50)), PixelArtOptions(mode="photo"))
    with pytest.raises(ValueError):
        generate_pixel_art(garment(), PixelArtOptions(mode="hybrid"), anchors=None)
    with pytest.raises(ValueError, match="needs the garment's SpriteRecipe"):
        generate_pixel_art(garment(), PixelArtOptions(mode="combined"), ANCHORS)
    with pytest.raises(ValueError, match="integer multiple"):
        generate_pixel_art(garment(), PixelArtOptions(mode="hybrid", sprite_size=96, preview_size=512), ANCHORS)
    with pytest.raises(UnsupportedImage):
        load_image(b"definitely not an image")


def test_worn_shoes_have_no_clothing_segmentation():
    cut, warnings = cut_out_worn_garment(garment(), "shoes")
    assert cut is None and "person may show" in warnings[0]


def _png(img):
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_upload_flow_end_to_end(tmp_path):
    spriter = GemmaSpriter(provider="test")
    data = _png(garment())
    gen = asyncio.run(generate_item(data, spriter, hint="hoodie", filename="x.png",
                                    pixel_art=PixelArtOptions()))
    item = save_item(gen, tmp_path)
    assert item["pixel_art"]["status"] == "ready"
    assert (tmp_path / item["pixel_art"]["sprite"]).exists()
    assert (tmp_path / item["original"]).read_bytes() == data                # original kept untouched
    assert Image.open(tmp_path / item["sprite_large"]).size == (256, 256)  # template sprite still made

    (tmp_path / "wardrobe.json").write_text(json.dumps([{**item, "name": "</script><b>x"}]))
    page = build_gallery(tmp_path).read_text()
    assert "</script><b>" not in page and "image-rendering: pixelated" in page


def test_segmentation_failure_keeps_template_sprite(tmp_path):
    spriter = GemmaSpriter(provider="test")
    gen = asyncio.run(generate_item(_png(Image.new("RGBA", (200, 200))), spriter, hint="hoodie",
                                    pixel_art=PixelArtOptions()))
    item = save_item(gen, tmp_path)
    assert item["pixel_art"]["status"] == "failed"
    assert any("pixel art failed" in w for w in item["warnings"])
    assert (tmp_path / item["sprite"]).exists() and "sprite" not in item["pixel_art"]


# ---------------------------------------------------------------- combined --

def _sprite(img, recipe, anchors=ANCHORS, n=40):
    r = generate_pixel_art(img, PixelArtOptions(mode="combined", sprite_size=n, preview_size=n * 8),
                           anchors, recipe)
    return np.asarray(r["sprite"]), r


def test_combined_has_outline_ring_in_dark_tone():
    sprite, _ = _sprite(garment(), RECIPE)
    a = sprite[..., 3] > 0
    row = np.nonzero(a[20])[0]
    edge = sprite[20, row[0], :3].astype(int)          # leftmost opaque pixel = outline
    assert edge.sum() < np.array(YELLOW).sum() * 0.6


def test_combined_letter_glyph_replaces_print_at_print_location():
    recipe = SpriteRecipe("hoodie", "#e1bd30", accent="#111a40", graphic="letter", graphic_letter="P", seed="t")
    sprite, _ = _sprite(garment(), recipe)
    navy = (np.abs(sprite[..., :3].astype(int) - NAVY).sum(-1) < 60) & (sprite[..., 3] > 0)
    ys, xs = np.nonzero(navy)
    drawn = navy[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    assert ["".join("1" if v else "0" for v in row) for row in drawn] == ["110", "101", "110", "100", "100"]
    # garment() puts the print left of center, upper half: the glyph must land there, not at a fixed spot
    assert xs.mean() < 20 and ys.mean() < 20


def _navy(sprite):
    return (np.abs(sprite[..., :3].astype(int) - NAVY).sum(-1) < 60) & (sprite[..., 3] > 0)


def test_combined_strip_along_the_edge_is_not_a_graphic():
    """An accent-colored band running off the garment's edge (undershirt hem) is painted as fabric."""
    img = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
    img.paste((*YELLOW, 255), (50, 100, 350, 300))
    img.paste((*NAVY, 255), (50, 285, 350, 300))
    sprite, r = _sprite(img, SpriteRecipe("hoodie", "#e1bd30", accent="#111a40", graphic="none", seed="t"))
    assert _navy(sprite).sum() == 0 and r["graphic_drawn"] is None


def _with_print(w, h, colors=(NAVY,)):
    """Yellow garment with a centered print of w x h (fraction of the garment), in vertical color bands."""
    img = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
    img.paste((*YELLOW, 255), (50, 100, 350, 300))
    pw, ph = int(300 * w), int(200 * h)
    x0, y0 = 200 - pw // 2, 170 - ph // 2
    for i, col in enumerate(colors):
        img.paste((*col, 255), (x0 + i * pw // len(colors), y0, x0 + (i + 1) * pw // len(colors), y0 + ph))
    return img


def test_small_marking_is_dropped():
    sprite, r = _sprite(_with_print(0.08, 0.06), SpriteRecipe("hoodie", "#e1bd30", accent="#111a40",
                                                              graphic="logo", seed="t"))
    assert _navy(sprite).sum() == 0 and r["graphic_drawn"] is None


def test_big_graphic_is_detected_even_if_gemma_missed_it():
    """Two-color graphic Gemma didn't report (graphic none, no accent): drawn from the photo, both colors."""
    red = (200, 40, 50)
    sprite, r = _sprite(_with_print(0.4, 0.3, colors=(NAVY, red)), SpriteRecipe("hoodie", "#e1bd30", seed="t"),
                        anchors=[Anchor("#e1bd30", "primary")])
    reds = (np.abs(sprite[..., :3].astype(int) - red).sum(-1) < 60) & (sprite[..., 3] > 0)
    assert r["graphic_drawn"] == "photo"
    assert _navy(sprite).sum() >= 10 and reds.sum() >= 10


def test_patterned_fabric_has_no_graphic_detection():
    sprite, r = _sprite(_with_print(0.4, 0.3), SpriteRecipe("tshirt", "#e1bd30", secondary="#111a40",
                                                            pattern="striped", seed="t"),
                        anchors=[Anchor("#e1bd30", "primary"), Anchor("#111a40", "secondary")])
    assert r["graphic_drawn"] is None


def test_combined_applies_gemma_pattern():
    plain, _ = _sprite(garment(), SpriteRecipe("tshirt", "#e1bd30", secondary="#111a40", seed="t"),
                       anchors=[Anchor("#e1bd30", "primary"), Anchor("#111a40", "secondary")])
    striped, _ = _sprite(garment(), SpriteRecipe("tshirt", "#e1bd30", secondary="#111a40",
                                                  pattern="striped", seed="t"),
                         anchors=[Anchor("#e1bd30", "primary"), Anchor("#111a40", "secondary")])
    col = lambda s: (np.abs(s[8:32, 20, :3].astype(int) - NAVY).sum(-1) < 60).sum()
    assert col(striped) > col(plain) + 4


# ------------------------------------------------------------ graphic text --

from wardrobe_pixels.pixelate import _text_rows, choose_graphic, text_fallbacks  # noqa: E402
from wardrobe_pixels.spec import GarmentSpec  # noqa: E402


def test_text_rows_width_and_spacing():
    assert len(_text_rows("PITT")[0]) == 4 * 3 + 3       # 3px letters, 1px gaps
    assert len(_text_rows("N Y")[0]) == len(_text_rows("NY")[0]) + 1   # word gap 2px vs letter gap 1px
    assert _text_rows("??") is None


def test_text_fallback_order():
    assert text_fallbacks("NEW YORK", "letter") == ["NEW YORK", "NY", "N"]
    assert text_fallbacks("PITT", "letter") == ["PITT", "P"]
    assert text_fallbacks("JUST DO IT", "text") == ["JUST DO IT"]   # slogans never shrink to initials


def _recipe(text, graphic="letter"):
    return SpriteRecipe("hoodie", "#e1bd30", accent="#111a40", graphic=graphic,
                        graphic_letter=text[0], seed="t", extra={"graphic_text": text})


@pytest.mark.parametrize("width,expected", [(30, "PITT"), (12, "P")])
def test_choose_graphic_fits_the_fabric(width, expected):
    mask = np.zeros((40, 40), bool)
    mask[5:35, 20 - width // 2:20 - width // 2 + width] = True
    rows, scale, drawn = choose_graphic(_recipe("PITT"), mask, 20, 15, print_height=4)
    assert drawn == expected and scale == 1 and len(rows[0]) <= width - 4


def test_slogan_that_does_not_fit_keeps_photo_shape():
    mask = np.zeros((40, 40), bool)
    mask[5:35, 14:26] = True
    assert choose_graphic(_recipe("STAY WILD", "text"), mask, 20, 15, print_height=4) is None


def test_combined_draws_full_word_from_gemma_text():
    img = garment(320, 220)
    sprite, r = _sprite(img, _recipe("PITT"))
    assert r["graphic_drawn"] == "PITT"
    navy = (np.abs(sprite[..., :3].astype(int) - NAVY).sum(-1) < 60) & (sprite[..., 3] > 0)
    ys, xs = np.nonzero(navy)
    drawn = navy[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    assert ["".join("1" if v else "0" for v in row) for row in drawn] == _text_rows("PITT")


def test_spec_normalizes_graphic_text_and_derives_letter():
    spec = GarmentSpec(name="x", subtype="hoodie", pattern="solid", primary_color=0,
                       graphic="letter", graphic_text="  pitt! ")
    assert spec.graphic_text == "PITT" and spec.graphic_letter == "P"


# ------------------------------------------------------------------ shaped --

from wardrobe_pixels.render import render_sprite  # noqa: E402
from wardrobe_pixels.templates import TEMPLATES  # noqa: E402


def _shaped(img, recipe, anchors):
    return generate_pixel_art(img, PixelArtOptions(mode="shaped"), anchors, recipe)


def _hoodie_photo(hood_lining=True, print_=True):
    """Yellow garment; navy lining at the top center (like an open hood) and a navy chest print."""
    img = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
    img.paste((*YELLOW, 255), (50, 60, 350, 340))
    if hood_lining:
        img.paste((*NAVY, 255), (170, 70, 230, 110))
    if print_:
        img.paste((*NAVY, 255), (130, 160, 270, 190))
    return img


SHAPED_RECIPE = SpriteRecipe("hoodie", "#e1bd30", secondary="#111a40", accent="#111a40", graphic="letter",
                             graphic_letter="P", seed="t", extra={"graphic_text": "PITT"})
SHAPED_ANCHORS = [Anchor("#e1bd30", "primary"), Anchor("#111a40", "secondary")]


def test_shaped_uses_the_template_silhouette_exactly():
    r = _shaped(_hoodie_photo(), SHAPED_RECIPE, SHAPED_ANCHORS)
    template = np.asarray(render_sprite(SHAPED_RECIPE))
    assert r["sprite"].size == (32, 32) and r["preview"].size == (256, 256)
    assert (np.asarray(r["sprite"])[..., 3] == template[..., 3]).all()      # same shape + outline


def test_shaped_trim_follows_the_photo():
    """Template draws cuffs/hem in the trim color; the photo shows them as fabric, so they're fabric."""
    sprite = np.asarray(_shaped(_hoodie_photo(), SHAPED_RECIPE, SHAPED_ANCHORS)["sprite"])
    trim = np.array([list(r) for r in TEMPLATES["hoodie"].rows]) == "t"
    navy_trim = (np.abs(sprite[trim][:, :3].astype(int) - NAVY).sum(-1) < 90).mean()
    assert navy_trim < 0.1


def test_shaped_hood_lining_and_text_come_from_the_photo():
    r = _shaped(_hoodie_photo(), SHAPED_RECIPE, SHAPED_ANCHORS)
    sprite = np.asarray(r["sprite"])
    navy = _navy(sprite)
    assert navy[2:8, 12:20].sum() >= 4                  # hood opening drawn as the lining color
    assert r["graphic_drawn"] == "PITT"
    rows = np.nonzero(navy[9:20].any(1))[0]
    assert len(rows) >= 5                               # 5 rows of 3x5 lettering on the chest


def test_shaped_without_graphic_or_lining_is_plain_template_shape():
    r = _shaped(_hoodie_photo(hood_lining=False, print_=False),
                SpriteRecipe("hoodie", "#e1bd30", seed="t"), [Anchor("#e1bd30", "primary")])
    assert r["graphic_drawn"] is None and _navy(np.asarray(r["sprite"])).sum() == 0


def test_shaped_deterministic():
    a = _shaped(_hoodie_photo(), SHAPED_RECIPE, SHAPED_ANCHORS)
    b = _shaped(_hoodie_photo(), SHAPED_RECIPE, SHAPED_ANCHORS)
    assert a["sprite"].tobytes() == b["sprite"].tobytes()


def test_shaped_outline_under_fabric_trim_is_not_trim_colored():
    sprite = np.asarray(_shaped(_hoodie_photo(), SHAPED_RECIPE, SHAPED_ANCHORS)["sprite"])
    grid = np.array([list(r) for r in TEMPLATES["hoodie"].rows])
    below_hem = sprite[26, 8:24]                      # outline row under the hem band (rows 24-25)
    assert (below_hem[:, 3] == 255).all()
    plain = np.asarray(render_sprite(SpriteRecipe("hoodie", "#e1bd30", seed="t", snap_to_palette=False)))
    assert (below_hem == plain[26, 8:24]).all()       # same outline as an all-fabric hoodie
    assert grid[26, 8] == "."
