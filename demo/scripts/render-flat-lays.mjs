import { pipeline } from "@huggingface/transformers";
import sharp from "sharp";
import { readdir } from "node:fs/promises";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const sourceDir = join(root, "images");
const outputDir = join(root, "rendered");
const segmenter = await pipeline("background-removal", "onnx-community/ormbg-ONNX", {
  dtype: "q8",
});

const requested = process.argv.slice(2);
const filenames = requested.length
  ? requested.map((name) => name.endsWith(".jpg") ? name : `${name}.jpg`)
  : (await readdir(sourceDir)).filter((file) => file.endsWith(".jpg")).sort();

for (const name of filenames) {
  const cutout = (await segmenter(join(sourceDir, name)))[0];
  if (cutout.channels !== 4) throw new Error(`${name}: expected RGBA output`);
  const { width, height, data } = cutout;
  let minX = width, minY = height, maxX = 0, maxY = 0, count = 0;
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      if (data[(y * width + x) * 4 + 3] < 75) continue;
      minX = Math.min(minX, x);
      minY = Math.min(minY, y);
      maxX = Math.max(maxX, x);
      maxY = Math.max(maxY, y);
      count++;
    }
  }
  if (count < width * height * 0.01) throw new Error(`${name}: foreground not found`);
  const left = Math.max(0, minX - 8);
  const top = Math.max(0, minY - 8);
  const cropWidth = Math.min(width - left, maxX - left + 9);
  const cropHeight = Math.min(height - top, maxY - top + 9);
  const raw = sharp(Buffer.from(data), { raw: { width, height, channels: 4 } });
  const { data: resized, info } = await raw
    .extract({ left, top, width: cropWidth, height: cropHeight })
    .resize(760, 760, { fit: "inside" })
    .png()
    .toBuffer({ resolveWithObject: true });
  const target = join(outputDir, name.replace(/\.jpg$/, ".png"));
  await sharp({
    create: { width: 900, height: 900, channels: 4, background: { r: 255, g: 255, b: 255, alpha: 0 } }
  })
    .composite([{ input: resized, left: Math.round((900 - info.width) / 2), top: Math.round((900 - info.height) / 2) }])
    .png()
    .toFile(target);
  console.log(`${name} -> ${target}`);
}
