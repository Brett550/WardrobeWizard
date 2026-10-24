import { readdir } from "node:fs/promises";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import sharp from "sharp";
import { createWeeklyPlan } from "../server.mjs";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const names = (await readdir(join(root, "rendered"))).filter((name) => name.endsWith(".png")).sort();
const selected = process.argv.includes("--minimal")
  ? ["pants", "shirt", "shoes"].map((prefix) => names.find((name) => name.startsWith(prefix)))
  : names;
const items = await Promise.all(selected.map(async (filename, index) => {
  const category = filename.startsWith("shirt") ? "shirts" : filename.startsWith("pants") ? "pants" : "shoes";
  const image = await sharp(join(root, "rendered", filename))
    .resize(384, 384, { fit: "contain", background: "#ffffff" })
    .flatten({ background: "#ffffff" })
    .jpeg({ quality: 76 })
    .toBuffer();
  return {
    id: `WA-${String(index + 1).padStart(3, "0")}`,
    name: filename.replace(".png", "").replaceAll("-", " "),
    category,
    image: image.toString("base64")
  };
}));
const key = process.env.GEMINI_API_KEY || process.env.GOOGLE_API_KEY;
if (!key) throw new Error("Set GEMINI_API_KEY before running the Gemma smoke test.");
const plan = await createWeeklyPlan(items, key);
console.log(`Gemma 4 returned ${plan.length} complete days.`);
for (const day of plan) console.log(`${day.day}: ${day.shirt} / ${day.pants} / ${day.shoes}`);
