"""Accept any image the user throws at us and normalize it to a clean RGBA image / PNG.

Handles JPEG, PNG, WEBP, GIF (first frame), BMP, TIFF, ICO out of the box.
HEIC/HEIF (iPhone photos): pip install pillow-heif
AVIF: supported by recent Pillow builds; otherwise pip install pillow-avif-plugin
SVG: pip install cairosvg
"""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_SIDE = 1600  # plenty for Gemma and segmentation; keeps uploads fast
MAX_PIXELS = 50_000_000  # 48 MP phone photos fit; tiny files that decode to gigabytes don't

_plugins_loaded = False


def _load_optional_plugins():
    global _plugins_loaded
    if _plugins_loaded:
        return
    _plugins_loaded = True
    try:
        from pillow_heif import register_heif_opener  # type: ignore
        register_heif_opener()
    except ImportError:
        pass
    try:
        import pillow_avif  # type: ignore  # noqa: F401  (registers itself)
    except ImportError:
        pass


def _sniff(data: bytes) -> str:
    head = data[:32]
    if head[4:12] in (b"ftypheic", b"ftypheix", b"ftypmif1", b"ftypmsf1", b"ftyphevc"):
        return "heic"
    if head[4:12] in (b"ftypavif", b"ftypavis"):
        return "avif"
    if head.lstrip().startswith(b"<svg") or b"<svg" in data[:512]:
        return "svg"
    return "other"


class UnsupportedImage(ValueError):
    pass


def load_image(source: str | Path | bytes) -> Image.Image:
    """Path or raw bytes (e.g. an upload) -> RGBA PIL image, upright, 8-bit, size-capped."""
    _load_optional_plugins()
    data = Path(source).read_bytes() if isinstance(source, (str, Path)) else bytes(source)
    kind = _sniff(data)

    if kind == "svg":
        try:
            import cairosvg  # type: ignore
        except ImportError as e:
            raise UnsupportedImage("SVG upload needs `pip install cairosvg`") from e
        try:
            data = cairosvg.svg2png(bytestring=data, output_width=1024)
        except Exception as e:
            raise UnsupportedImage(f"could not read SVG ({e})") from e

    try:
        img = Image.open(io.BytesIO(data))
        if img.width * img.height > MAX_PIXELS:  # checked from the header, before decoding
            raise UnsupportedImage(f"image too large ({img.width}x{img.height}; max {MAX_PIXELS // 10**6} MP)")
        img.load()
    except Image.DecompressionBombError as e:
        raise UnsupportedImage("image too large") from e
    except UnidentifiedImageError as e:
        hint = {"heic": "install pillow-heif for iPhone photos",
                "avif": "install pillow-avif-plugin"}.get(kind, "unrecognized image format")
        raise UnsupportedImage(f"could not read image ({hint})") from e

    if getattr(img, "n_frames", 1) > 1:
        img.seek(0)  # animated GIF/WEBP: use the first frame

    img = ImageOps.exif_transpose(img)  # phone photos are often stored sideways

    # Normalize odd modes: 16-bit, CMYK, palette (with transparency), grayscale+alpha...
    if img.mode in ("I;16", "I;16B", "I;16L", "I"):
        img = img.point(lambda v: v / 256).convert("L")
    elif img.mode == "F":
        img = img.convert("L")
    if img.mode == "P" and "transparency" in img.info:
        img = img.convert("RGBA")
    img = img.convert("RGBA")

    if max(img.size) > MAX_SIDE:
        img.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    return img


def to_png_bytes(img: Image.Image, flatten_on: tuple[int, int, int] | None = None) -> bytes:
    """Encode as PNG. If flatten_on is given, composite transparency onto that color first."""
    if flatten_on is not None:
        bg = Image.new("RGBA", img.size, (*flatten_on, 255))
        bg.alpha_composite(img.convert("RGBA"))
        img = bg.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
