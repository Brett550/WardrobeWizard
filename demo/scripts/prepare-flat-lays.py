"""Download and crop the nine overhead sample photos from Pexels."""

from io import BytesIO
from pathlib import Path
from urllib.request import Request, urlopen

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
INPUTS = ROOT / "images"
SOURCES = {
    # filename: (Pexels photo ID, requested width, crop at that width)
    "shirt-white-tee": (12025472, 1400, None),
    "shirt-black-flat-tee": (6046205, 1400, (0, 540, 1400, 1900)),
    "shirt-cream-knit": (6046231, 1400, (45, 265, 1310, 1730)),
    "pants-brown-lace": (6046228, 1400, (145, 340, 1160, 1810)),
    "pants-taupe-folded": (33633245, 1800, (165, 180, 850, 1160)),
    "pants-indigo-denim": (18533673, 1800, (990, 565, 1710, 1410)),
    "shoes-monochrome-slipons": (35618109, 1400, None),
    "shoes-pink-runner": (6748330, 1400, None),
    "shoes-taupe-boot": (8408556, 1400, (380, 1290, 1100, 1720)),
}


def download(photo_id, width):
    cached = ROOT / "candidates" / f"{photo_id}.jpg"
    if cached.exists():
        return Image.open(cached).convert("RGB")
    url = (
        f"https://images.pexels.com/photos/{photo_id}/"
        f"pexels-photo-{photo_id}.jpeg?auto=compress&cs=tinysrgb&w={width}"
    )
    request = Request(url, headers={"User-Agent": "WardrobeArchive/1.0"})
    with urlopen(request, timeout=30) as response:
        return Image.open(BytesIO(response.read())).convert("RGB")


def main():
    INPUTS.mkdir(exist_ok=True)
    for name, (photo_id, width, box) in SOURCES.items():
        image = download(photo_id, width)
        if box is not None:
            factor = image.width / width
            image = image.crop(tuple(round(value * factor) for value in box))
        image.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
        target = INPUTS / f"{name}.jpg"
        image.save(target, quality=90, optimize=True)
        print(f"{name}: Pexels {photo_id} -> {image.size}")


if __name__ == "__main__":
    main()
