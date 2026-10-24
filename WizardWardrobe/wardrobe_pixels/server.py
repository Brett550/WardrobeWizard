"""Minimal API for the frontend.  pip install fastapi uvicorn python-multipart

  WARDROBE_PROVIDER=google GEMINI_API_KEY=... uvicorn wardrobe_pixels.server:app --reload

POST /sprites           multipart upload (field "file", optional "hint", "pixel_art" = shaped|combined|hybrid|photo|off)
                        -> item JSON + base64 PNGs (template sprite + photo-derived pixel_art sprite)
POST /sprites/rerender  edited item JSON -> fresh sprite PNGs (no model call)
POST /drip/chat         chat + app snapshot -> Drip's reply and validated actions (drip.py)
POST /plan/week         closet + forecast + style -> Gemma's validated outfits by item id (planner.py)
GET  /health            {"ok", provider, model}: the page uses it to switch out of demo mode
GET  /                  the front end (wardrobe_wizard_v2.html), same origin as the API
GET  /catalog/...       demo closet photos (next to the page)
"""
from __future__ import annotations

import base64
import io
import os
from pathlib import Path

from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .agent import GemmaSpriter, SpriteGenerationError
from .drip import DripError, DripRequest, DripResponse, build_drip, chat
from .planner import PlanError, PlanRequest, WeekPlan, build_planner, plan_week
from .generate import SPRITE_SCALE, generate_item, recipe_from_item
from .pixelate import PixelArtOptions
from .ingest import UnsupportedImage
from .render import render_sprite

app = FastAPI(title="Wardrobe Wizard sprites")
# Only pages on this machine may call the API; "*" would let any website spend the Gemma quota.
app.add_middleware(CORSMiddleware, allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?",
                   allow_methods=["GET", "POST"], allow_headers=["*"])
spriter = GemmaSpriter.from_env()
MAX_UPLOAD_BYTES = 20 * 2**20
PAGE = Path(os.getenv("WARDROBE_PAGE", Path(__file__).resolve().parent.parent / "wardrobe_wizard_v2.html"))
_drip = None
_planner = None
if (PAGE.parent / "catalog").is_dir():
    app.mount("/catalog", StaticFiles(directory=PAGE.parent / "catalog"), name="catalog")


def drip_agent():
    global _drip
    if _drip is None:
        _drip = build_drip(os.getenv("WARDROBE_PROVIDER", "google"), os.getenv("WARDROBE_MODEL") or None)
    return _drip


def planner_agent():
    global _planner
    if _planner is None:
        _planner = build_planner(os.getenv("WARDROBE_PROVIDER", "google"), os.getenv("WARDROBE_MODEL") or None)
    return _planner


@app.get("/")
async def page():
    if not PAGE.exists():
        raise HTTPException(404, f"front end not found at {PAGE} (set WARDROBE_PAGE)")
    return FileResponse(PAGE, media_type="text/html")


@app.get("/health")
async def health():
    return {"ok": True, "provider": spriter.provider, "model": spriter.model_name}


@app.post("/drip/chat", response_model=DripResponse)
async def drip_chat(req: DripRequest):
    try:
        return await chat(drip_agent(), req)
    except DripError as e:
        raise HTTPException(502, str(e))


def _b64(img) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


@app.post("/sprites")
async def create_sprite(file: UploadFile = File(...), hint: str | None = Form(None),
                        pixel_art: str = Form("shaped")):
    if pixel_art not in ("shaped", "combined", "hybrid", "photo", "off"):
        raise HTTPException(422, "pixel_art must be shaped, combined, hybrid, photo or off")
    data = await file.read(MAX_UPLOAD_BYTES + 1)  # never read more than the limit into memory
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"upload larger than {MAX_UPLOAD_BYTES // 2**20} MB")
    px = None if pixel_art == "off" else PixelArtOptions(
        mode=pixel_art, **({"sprite_size": 96, "preview_size": 768} if pixel_art == "hybrid" else {}))
    try:
        gen = await generate_item(data, spriter, hint=hint, filename=file.filename, pixel_art=px)
    except UnsupportedImage as e:
        raise HTTPException(415, str(e))
    except SpriteGenerationError as e:
        raise HTTPException(502, str(e))
    out = {**gen.item, "sprite_png": _b64(gen.sprite), "sprite_large_png": _b64(gen.sprite_large),
           "cutout_png": _b64(gen.cutout)}
    if gen.pixel_art:
        out["pixel_art"] = {**gen.item["pixel_art"], "sprite_png": _b64(gen.pixel_art["sprite"]),
                            "preview_png": _b64(gen.pixel_art["preview"])}
    return out


@app.post("/sprites/rerender")
async def rerender(item: dict = Body(...)):
    try:
        recipe = recipe_from_item(item)
        return {"sprite_png": _b64(render_sprite(recipe)),
                "sprite_large_png": _b64(render_sprite(recipe, scale=SPRITE_SCALE))}
    except (KeyError, ValueError, TypeError, AttributeError) as e:
        raise HTTPException(422, f"bad item: {e}")


@app.post("/plan/week", response_model=WeekPlan)
async def plan(req: PlanRequest):
    try:
        return await plan_week(planner_agent(), req)
    except PlanError as e:
        raise HTTPException(502, str(e))
