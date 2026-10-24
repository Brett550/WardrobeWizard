import sharp from "sharp";

const categories = ["shirts", "pants", "shoes"];
const tileWidth = 232;
const tileHeight = 258;
const photoSize = 208;

export async function createWardrobeBoards(items) {
  const boards = [];
  for (const category of categories) {
    const group = items.filter((item) => item.category === category);
    if (!group.length) continue;
    const columns = Math.min(5, group.length);
    const rows = Math.ceil(group.length / columns);
    const width = columns * tileWidth;
    const height = rows * tileHeight;
    const overlays = [];
    for (const [index, item] of group.entries()) {
      const left = (index % columns) * tileWidth;
      const top = Math.floor(index / columns) * tileHeight;
      const photo = await sharp(Buffer.from(item.image, "base64"))
        .resize(photoSize, photoSize, { fit: "contain", background: "#ffffff" })
        .png()
        .toBuffer();
      const label = Buffer.from(
        `<svg width="${tileWidth}" height="30" xmlns="http://www.w3.org/2000/svg">`
        + `<text x="116" y="21" text-anchor="middle" font-family="monospace" font-size="17" fill="#111">${item.id}</text></svg>`
      );
      overlays.push({ input: photo, left: left + 12, top: top + 8 });
      overlays.push({ input: label, left, top: top + 216 });
    }
    const image = await sharp({
      create: { width, height, channels: 3, background: "#ffffff" }
    })
      .composite(overlays)
      .jpeg({ quality: 82 })
      .toBuffer();
    boards.push({ category, image: image.toString("base64") });
  }
  return boards;
}
