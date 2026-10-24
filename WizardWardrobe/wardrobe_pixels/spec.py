"""GarmentSpec: what Gemma must return. Pydantic AI validates it and re-asks on failure.

Before-validators quietly fix harmless variations ("Hoodie", "t-shirt", "stripes",
warmth 7) so we don't spend a retry on them. Real mistakes (an unknown garment type,
a color index that doesn't exist) fail validation and Gemma is asked again.
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .render import GRAPHICS, PATTERNS, SpriteRecipe
from .templates import SUBTYPES, TEMPLATES

Subtype = Literal[tuple(SUBTYPES)]    # type: ignore[valid-type]  single source of truth: templates.py
Pattern = Literal[tuple(PATTERNS)]    # type: ignore[valid-type]
Graphic = Literal[tuple(GRAPHICS)]    # type: ignore[valid-type]

SUBTYPE_SYNONYMS = {
    "t-shirt": "tshirt", "t shirt": "tshirt", "tee": "tshirt", "tank": "tshirt", "tank top": "tshirt",
    "polo": "tshirt", "jersey": "tshirt",
    "long sleeve": "longsleeve", "long-sleeve": "longsleeve", "long sleeve shirt": "longsleeve",
    "sweater": "longsleeve", "sweatshirt": "longsleeve", "crewneck": "longsleeve",
    "cardigan": "longsleeve", "jacket": "longsleeve", "button-up": "longsleeve",
    "flannel": "longsleeve", "shirt": "longsleeve",
    "hoody": "hoodie", "zip-up": "hoodie", "zip hoodie": "hoodie",
    "jeans": "pants", "trousers": "pants", "joggers": "pants", "sweatpants": "pants",
    "chinos": "pants", "cargo pants": "pants", "leggings": "pants",
    "short": "shorts",
    "shoes": "sneakers", "shoe": "sneakers", "sneaker": "sneakers", "trainers": "sneakers",
    "hat": "cap", "baseball cap": "cap", "fitted": "cap", "snapback": "cap",
    "trucker hat": "cap", "dad hat": "cap", "toque": "beanie", "knit hat": "beanie",
    "bucket hat": "bucket", "fisherman hat": "bucket",
    "high tops": "hightops", "high-tops": "hightops", "high top": "hightops", "boots": "hightops",
    "boot": "hightops", "chuck": "hightops",
    "sock": "socks", "crew socks": "socks", "ankle socks": "socks",
}
PATTERN_SYNONYMS = {
    "plain": "solid", "none": "solid", "stripes": "striped", "horizontal stripes": "striped",
    "vertical stripes": "vertical_striped", "pinstripe": "vertical_striped",
    "polka dots": "polka_dot", "dots": "polka_dot", "dotted": "polka_dot",
    "check": "checkered", "checked": "checkered", "gingham": "checkered",
    "tartan": "plaid", "flannel": "plaid", "flowers": "floral", "camouflage": "camo",
    "jean": "denim",
}
GRAPHIC_SYNONYMS = {"words": "text", "logo text": "text", "number": "letter", "print": "logo"}


def _canon(value, allowed: list[str], synonyms: dict[str, str]):
    if not isinstance(value, str):
        return value
    v = value.strip().lower().replace("_", " ")
    for a in allowed:
        if v == a.replace("_", " "):
            return a
    return synonyms.get(v, value)  # unknown -> leave as-is so Literal validation reports it


def _clamp(v, lo=1, hi=5):
    try:
        return max(lo, min(hi, int(round(float(v)))))
    except (TypeError, ValueError):
        return v


class GarmentSpec(BaseModel):
    """A sprite recipe for one clothing item, described from its photo."""

    name: str = Field(description="Short cute display name, max 4 words, e.g. 'Cozy Navy Hoodie'")
    subtype: Subtype = Field(description="Garment template, chosen by shape")
    pattern: Pattern = Field(description="Fabric pattern. Use 'denim' for jeans and denim jackets")
    primary_color: int = Field(ge=0, description="Index of the main fabric color in the measured list")
    secondary_color: int | None = Field(
        default=None, description="Index of a second fabric/trim color (stripes, plaid, collar, cuffs, "
                                  "soles, brim), or null")
    accent_color: int | None = Field(
        default=None, description="Index of the color of a printed graphic or logo, or null")
    graphic: Graphic = Field(
        default="none", description="Printed design on the chest/front. 'letter' if it is mainly "
                                    "one letter or number")
    graphic_letter: str | None = Field(
        default=None, description="The single letter or digit when graphic is 'letter', else null")
    graphic_text: str | None = Field(
        default=None, description="The printed word(s) exactly as they appear, letters/digits/spaces "
                                  "only, e.g. 'PITT' or 'NEW YORK'. Null if the print has no lettering")
    warmth: int = Field(default=3, ge=1, le=5, description="1 = tank top, 5 = heavy winter layer")
    formality: int = Field(default=2, ge=1, le=5, description="1 = gym/lounge, 5 = formal")
    vibe_tags: list[str] = Field(default_factory=list, description="Up to 4 short style words")
    worn: bool = Field(default=False, description="True if a person is wearing the garment in the photo "
                                                   "(face, hands, skin or other clothes visible)")

    # --- forgiving normalization (no retry needed) ---------------------------------

    @field_validator("subtype", mode="before")
    @classmethod
    def _subtype(cls, v):
        return _canon(v, SUBTYPES, SUBTYPE_SYNONYMS)

    @field_validator("pattern", mode="before")
    @classmethod
    def _pattern(cls, v):
        return _canon(v or "solid", PATTERNS, PATTERN_SYNONYMS)

    @field_validator("graphic", mode="before")
    @classmethod
    def _graphic(cls, v):
        return _canon(v or "none", GRAPHICS, GRAPHIC_SYNONYMS)

    @field_validator("warmth", "formality", mode="before")
    @classmethod
    def _scale(cls, v):
        return _clamp(v)

    @field_validator("name", mode="after")
    @classmethod
    def _name(cls, v: str):
        return " ".join(v.split()[:5])[:40] or "Mystery Item"

    @field_validator("vibe_tags", mode="before")
    @classmethod
    def _tags_in(cls, v):
        if v is None:
            return []
        if isinstance(v, str):  # "cozy, streetwear" -> ["cozy", "streetwear"]
            return [t for t in re.split(r"[,/;]", v)]
        return v

    @field_validator("vibe_tags", mode="after")
    @classmethod
    def _tags(cls, v: list[str]):
        return [t.strip().lower()[:20] for t in v if t.strip()][:4]

    @field_validator("graphic_letter", mode="before")
    @classmethod
    def _letter(cls, v):
        if v is None:
            return None
        s = "".join(ch for ch in str(v) if ch.isalnum()).upper()
        return s[:1] or None

    @field_validator("graphic_text", mode="before")
    @classmethod
    def _text(cls, v):
        if v is None:
            return None
        s = " ".join("".join(ch if ch.isalnum() else " " for ch in str(v)).split()).upper()
        return s[:24] or None

    @model_validator(mode="after")
    def _graphic_consistency(self):
        if self.graphic == "letter" and not self.graphic_letter and self.graphic_text:
            self.graphic_letter = self.graphic_text[0]
        if self.graphic == "letter" and not self.graphic_letter:
            self.graphic = "logo"
        if self.graphic != "letter":
            self.graphic_letter = None
        if self.secondary_color == self.primary_color:
            self.secondary_color = None
        return self

    # --- conversion -----------------------------------------------------------------

    @property
    def category(self) -> str:
        return TEMPLATES[self.subtype].category

    def color_problems(self, n_colors: int) -> list[str]:
        """Index errors that depend on how many colors were measured (checked by the agent)."""
        problems = []
        for field in ("primary_color", "secondary_color", "accent_color"):
            i = getattr(self, field)
            if i is not None and not 0 <= i < n_colors:
                problems.append(f"{field}={i} does not exist; valid indices are 0 to {n_colors - 1}")
        return problems


def spec_to_recipe(spec, colors: list[dict], seed: str, snap_to_palette: bool = True) -> SpriteRecipe:
    """GarmentSpec + measured colors -> renderer input."""
    def hex_at(i):
        return colors[i]["hex"] if i is not None else None

    return SpriteRecipe(
        subtype=spec.subtype,
        primary=hex_at(spec.primary_color),
        secondary=hex_at(spec.secondary_color),
        accent=hex_at(spec.accent_color),
        pattern=spec.pattern,
        graphic=spec.graphic,
        graphic_letter=spec.graphic_letter,
        seed=seed,
        extra={"graphic_text": spec.graphic_text} if spec.graphic_text else {},
        snap_to_palette=snap_to_palette,
    )
