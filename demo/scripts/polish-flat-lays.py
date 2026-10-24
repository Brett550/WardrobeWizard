"""Finish the two sample cutouts where the background model kept the backdrop."""

from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
RENDERED = ROOT / "rendered"


def polygon_mask(size, polygons, feather=1.5):
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    for points in polygons:
        draw.polygon(points, fill=255)
    return mask.filter(ImageFilter.GaussianBlur(feather))


def center_product(image, margin=68):
    bbox = image.getbbox()
    image = image.crop(bbox)
    image.thumbnail((900 - 2 * margin, 900 - 2 * margin), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (900, 900), (255, 255, 255, 0))
    canvas.alpha_composite(image, ((900 - image.width) // 2, (900 - image.height) // 2))
    return canvas


def polish_cream_top():
    path = RENDERED / "shirt-cream-knit.png"
    image = Image.open(path).convert("RGBA")
    outline = [
        (454, 69), (494, 93), (573, 96), (627, 115), (715, 155),
        (738, 188), (751, 239), (775, 296), (802, 347), (804, 445),
        (710, 475), (690, 492), (658, 475), (646, 460), (635, 570),
        (633, 675), (620, 744), (599, 807), (565, 828), (503, 815),
        (426, 790), (330, 787), (255, 778), (228, 759), (222, 715),
        (218, 625), (217, 525), (218, 448), (211, 383), (173, 377),
        (147, 368), (107, 320), (107, 303), (143, 256), (196, 214),
        (237, 165), (281, 126), (314, 102), (366, 89), (422, 82),
    ]
    mask = polygon_mask(image.size, [outline], 2)
    alpha = Image.new("L", image.size)
    alpha.paste(Image.frombytes("L", image.size, image.getchannel("A").tobytes()))
    image.putalpha(Image.frombytes("L", image.size, bytes(
        a * b // 255 for a, b in zip(alpha.tobytes(), mask.tobytes())
    )))
    center_product(image).save(path)


def polish_slipons():
    image = Image.open(ROOT / "images" / "shoes-monochrome-slipons.jpg").convert("RGBA")
    rgb = np.array(image.convert("RGB"))
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    combined = np.zeros((image.height, image.width), dtype=np.uint8)
    for rectangle in [(55, 280, 400, 650), (250, 490, 350, 690)]:
        mask = np.zeros((image.height, image.width), dtype=np.uint8)
        cv2.grabCut(
            bgr, mask, rectangle,
            np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64),
            7, cv2.GC_INIT_WITH_RECT,
        )
        combined |= np.where(
            (mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0
        ).astype(np.uint8)
    red, green, blue = (
        rgb[:, :, channel].astype(np.int16) for channel in range(3)
    )
    backdrop = ((blue - red > 40) & (blue - green > 25)) | (
        (red - green > 10) & (red - blue > 8)
    )
    combined[backdrop] = 0
    image.putalpha(Image.fromarray(combined).filter(ImageFilter.GaussianBlur(0.8)))
    center_product(image).save(RENDERED / "shoes-monochrome-slipons.png")


if __name__ == "__main__":
    polish_cream_top()
    polish_slipons()
