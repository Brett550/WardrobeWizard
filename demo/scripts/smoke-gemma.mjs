import { readdir, mkdir, writeFile } from "node:fs/promises";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import sharp from "sharp";
import { createWeeklyPlan } from "../server.mjs";
import { createWardrobeBoards } from "../wardrobe-boards.mjs";

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
if (process.argv.includes("--preview")) {
  const boards = await createWardrobeBoards(items);
  const output = join(root, "candidates");
  await mkdir(output, { recursive: true });
  for (const board of boards) {
    await writeFile(join(output, `board-${board.category}.jpg`), Buffer.from(board.image, "base64"));
  }
  console.log(`Wrote ${boards.length} preview boards to ${output}`);
  process.exit(0);
}
const plan = await createWeeklyPlan(items, process.env.AWS_BEARER_TOKEN_BEDROCK);
console.log(`Gemma 3 12B IT returned ${plan.length} complete days.`);
for (const day of plan) console.log(`${day.day}: ${day.shirt} / ${day.pants} / ${day.shoes}`);
