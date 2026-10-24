"""Garment templates, drawn as ASCII so anyone on the team can edit them.

Legend
  .  transparent
  #  main fabric  -> primary color + pattern, auto-shaded
  t  trim         -> secondary color (collar, cuffs, soles, brims); falls back to primary
  d  detail line  -> dark outline color (pockets, seams, hood opening)
  l  light accent -> laces / drawstrings

Outlines are added automatically one pixel *outside* the silhouette, and
shading/highlights are added automatically, so templates only need flat
shapes. Symmetric garments are drawn as the LEFT HALF (16 cols) and mirrored.
Canvas is 32x32. Leave a 1px empty margin so the outline has room.
"""
from __future__ import annotations

from dataclasses import dataclass

SIZE = 32


@dataclass(frozen=True)
class Template:
    name: str
    category: str                       # top / bottom / shoes / hat / socks
    rows: tuple[str, ...]               # full 32-wide rows after mirroring
    graphic_anchor: tuple[int, int] | None  # (center_x, top_y) for prints/logos


def _build(half_rows: dict[int, str] | None = None, full_rows: dict[int, str] | None = None):
    rows = ["." * SIZE for _ in range(SIZE)]
    if half_rows:
        for y, half in half_rows.items():
            assert len(half) == SIZE // 2, f"row {y} has {len(half)} chars: {half!r}"
            rows[y] = half + half[::-1]
    if full_rows:
        for y, full in full_rows.items():
            assert len(full) == SIZE, f"row {y} has {len(full)} chars: {full!r}"
            rows[y] = full
    return tuple(rows)


def _fill(start: int, end: int, half: str) -> dict[int, str]:
    return {y: half for y in range(start, end + 1)}


TSHIRT = Template("tshirt", "top", _build({
    4: "......#####t....",
    5: "....########t...",
    6: "...##########ttt",
    7: "..##############",
    8: ".###############",
    9: ".###############",
    10: ".###############",
    11: ".tttttt#########",
    **_fill(12, 27, ".......#########"),
}), graphic_anchor=(16, 11))

LONGSLEEVE = Template("longsleeve", "top", _build({
    4: "......#####t....",
    5: "....########t...",
    6: "...##########ttt",
    7: "..##############",
    8: ".###############",
    9: ".###############",
    10: ".###############",
    **_fill(11, 22, ".#####.#########"),
    23: ".ttttt.#########",
    24: ".ttttt.#########",
    **_fill(25, 27, ".......#########"),
}), graphic_anchor=(16, 11))

HOODIE = Template("hoodie", "top", _build({
    2: "...........#####",
    3: "..........######",
    4: "......#######ddd",
    5: "....#########ddd",
    6: "...###########dd",
    7: "..###########l##",
    8: ".############l##",
    9: ".###############",
    10: ".###############",
    **_fill(11, 17, ".#####.#########"),
    18: ".#####.###dddddd",
    **_fill(19, 21, ".#####.###d#####"),
    22: ".ttttt.###d#####",
    23: ".ttttt.###d#####",
    24: ".......ttttttttt",
    25: ".......ttttttttt",
}), graphic_anchor=(16, 12))

PANTS = Template("pants", "bottom", _build({
    3: "......tttttttttt",
    4: "......tttttttttt",
    5: "......##########",
    6: "......#d########",
    7: "......##d#######",
    8: "......###d######",
    **_fill(9, 11, "......##########"),
    **_fill(12, 28, "......#########."),
}), graphic_anchor=None)

SHORTS = Template("shorts", "bottom", _build({
    6: "........tttttttt",
    7: "........tttttttt",
    8: "........########",
    9: "........#d######",
    10: "........##d#####",
    **_fill(11, 13, "........########"),
    **_fill(14, 20, ".......########."),
}), graphic_anchor=None)

SNEAKERS = Template("sneakers", "shoes", _build(full_rows={
    9: "....####........................",
    10: "...######.......................",
    11: "...#######......................",
    12: "...########l....................",
    13: "...#########l#..................",
    14: "...##########l##................",
    15: "...###########l####.............",
    16: "...################d###.........",
    17: "...#################d#####......",
    18: "...##################d#######...",
    19: "...##########################...",
    20: "..tttttttttttttttttttttttttttt..",
    21: "...tttttttttttttttttttttttttt...",
}), graphic_anchor=None)

CAP = Template("cap", "hat", _build({
    7: "...............t",
    8: "...........#####",
    9: ".........#######",
    10: "........########",
    11: ".......#########",
    12: "......##########",
    13: "......##########",
    **_fill(14, 17, ".....###########"),
    18: ".....ddddddddddd",
    19: "...ttttttttttttt",
    20: "..tttttttttttttt",
    21: "...ttttttttttttt",
}), graphic_anchor=(16, 12))


SOCKS = Template("socks", "socks", _build(full_rows={
    4: "........tttttttt................",
    5: "........tttttttt................",
    6: "........tttttttt................",
    **_fill(7, 17, "........########................"),
    18: "........#########...............",
    19: "........tt#########.............",
    20: "........ttt###########..........",
    21: "........ttt##########ttt........",
    22: ".........tt#########tttt........",
    23: "..........##########ttt.........",
}), graphic_anchor=None)

HIGHTOPS = Template("hightops", "shoes", _build(full_rows={
    4: "....########....................",
    **_fill(5, 11, "...#########l..................."),
    12: "...##########l##................",
    13: "...###########l####.............",
    14: "...################d###.........",
    15: "...#################d#####......",
    16: "...##################d#######...",
    17: "...##########################...",
    18: "..tttttttttttttttttttttttttttt..",
    19: "..tttttttttttttttttttttttttttt..",
    20: "...tttttttttttttttttttttttttt...",
}), graphic_anchor=None)

BEANIE = Template("beanie", "hat", _build({
    3: "..............ll",
    4: ".............lll",
    5: ".............lll",
    6: "...........#####",
    7: ".........#######",
    8: "........########",
    9: ".......#########",
    10: "......##########",
    **_fill(11, 15, ".....###########"),
    16: "....dddddddddddd",
    **_fill(17, 20, "....tttttttttttt"),
}), graphic_anchor=(16, 12))

BUCKET = Template("bucket", "hat", _build({
    8: "..........######",
    9: ".........#######",
    **_fill(10, 14, "........########"),
    15: "........dddddddd",
    16: "......##########",
    17: ".....###########",
    18: "....############",
    19: "...#############",
    20: "....############",
}), graphic_anchor=(16, 11))


TEMPLATES: dict[str, Template] = {t.name: t for t in
                                  [TSHIRT, LONGSLEEVE, HOODIE, PANTS, SHORTS, SNEAKERS, HIGHTOPS, CAP, BEANIE, BUCKET, SOCKS]}
SUBTYPES = list(TEMPLATES)
