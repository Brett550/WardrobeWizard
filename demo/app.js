const seedItems = [
  { id: "WA-001", code: "TS-01", name: "White Cotton Tee", category: "shirts", image: "rendered/shirt-white-tee.png", original: "images/shirt-white-tee.jpg" },
  { id: "WA-002", code: "TS-02", name: "Black Satin Tee", category: "shirts", image: "rendered/shirt-black-flat-tee.png", original: "images/shirt-black-flat-tee.jpg" },
  { id: "WA-003", code: "TS-03", name: "Cream Knit Top", category: "shirts", image: "rendered/shirt-cream-knit.png", original: "images/shirt-cream-knit.jpg" },
  { id: "WA-004", code: "PT-01", name: "Brown Cuffed Trousers", category: "pants", image: "rendered/pants-brown-lace.png", original: "images/pants-brown-lace.jpg" },
  { id: "WA-005", code: "PT-02", name: "Folded Taupe Trousers", category: "pants", image: "rendered/pants-taupe-folded.png", original: "images/pants-taupe-folded.jpg" },
  { id: "WA-006", code: "PT-03", name: "Dark Indigo Denim", category: "pants", image: "rendered/pants-indigo-denim.png", original: "images/pants-indigo-denim.jpg" },
  { id: "WA-007", code: "SN-01", name: "Monochrome Slip-Ons", category: "shoes", image: "rendered/shoes-monochrome-slipons.png", original: "images/shoes-monochrome-slipons.jpg" },
  { id: "WA-008", code: "SN-02", name: "White and Pink Trainers", category: "shoes", image: "rendered/shoes-pink-runner.png", original: "images/shoes-pink-runner.jpg" },
  { id: "WA-009", code: "BT-01", name: "Taupe Suede Boot", category: "shoes", image: "rendered/shoes-taupe-boot.png", original: "images/shoes-taupe-boot.jpg" }
];

const categories = ["shirts", "pants", "shoes"];
const $ = (selector) => document.querySelector(selector);
let segmenterPromise;
const state = {
  items: [...seedItems],
  filter: "all",
  query: "",
  currentItem: null,
  originalView: false,
  selectedFile: null,
  previewUrl: null,
  look: readStorage("wardrobe-archive-look", {}),
  savedLooks: readStorage("wardrobe-archive-saved-looks", [])
};

function readStorage(key, fallback) {
  try { return JSON.parse(localStorage.getItem(key)) ?? fallback; }
  catch { return fallback; }
}
function writeStorage(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); }
  catch { notify("BROWSER STORAGE IS UNAVAILABLE"); }
}
function formatCount(number) { return String(number).padStart(2, "0"); }
function findItem(id) { return state.items.find((item) => item.id === id); }
function notify(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("visible");
  clearTimeout(notify.timeout);
  notify.timeout = setTimeout(() => toast.classList.remove("visible"), 2900);
}

function renderCounts() {
  $("#total-count").textContent = formatCount(state.items.length);
  $("#count-all").textContent = formatCount(state.items.length);
  for (const category of categories) {
    $(`#count-${category}`).textContent = formatCount(state.items.filter((item) => item.category === category).length);
  }
  $("#look-count").textContent = formatCount(categories.filter((category) => state.look[category] && findItem(state.look[category])).length);
  $("#saved-count").textContent = formatCount(state.savedLooks.length);
}

function makeCard(item, index) {
  const article = document.createElement("article");
  article.className = "card";
  const button = document.createElement("button");
  button.className = "card-button";
  button.type = "button";
  button.setAttribute("aria-label", `View ${item.name}`);
  const imageWrap = document.createElement("span");
  imageWrap.className = "card-image";
  const image = document.createElement("img");
  image.src = item.image;
  image.alt = `${item.name} isolated on white`;
  image.loading = index < 3 ? "eager" : "lazy";
  imageWrap.append(image);
  const code = document.createElement("span");
  code.className = "card-code";
  code.textContent = item.code || item.id;
  button.append(imageWrap, code);
  button.addEventListener("click", () => openItem(item));
  article.append(button);
  return article;
}

function renderGrid() {
  const visible = state.items.filter((item) =>
    (state.filter === "all" || item.category === state.filter) &&
    (!state.query || `${item.name} ${item.category} ${item.id}`.toLowerCase().includes(state.query))
  );
  const grid = $("#item-grid");
  grid.replaceChildren(...visible.map(makeCard));
  $("#empty-state").hidden = visible.length !== 0;
  $(".sort-label").textContent = `SORTED / ${state.filter.toUpperCase()}`;
  renderCounts();
}

function openItem(item) {
  state.currentItem = item;
  state.originalView = false;
  $("#detail-image").src = item.image;
  $("#detail-image").alt = `${item.name} isolated on white`;
  $("#detail-title").textContent = item.name;
  $("#detail-category").textContent = `${item.category.toUpperCase()} / ${item.code || item.id}`;
  $("#detail-id").textContent = item.code || item.id;
  $("#detail-origin").textContent = item.uploaded ? "LOCAL UPLOAD" : "DEMO / PEXELS";
  $("#toggle-view").textContent = "VIEW ORIGINAL ↗";
  $("#delete-item").hidden = !item.uploaded;
  $("#add-to-look").innerHTML = `ADD TO LOOK <span>↗</span>`;
  $("#item-dialog").showModal();
}

function renderLook() {
  const slots = $("#look-slots");
  slots.replaceChildren();
  for (const category of categories) {
    const item = findItem(state.look[category]);
    const row = document.createElement("div");
    row.className = "look-slot";
    if (item) {
      const image = document.createElement("img");
      image.src = item.image;
      image.alt = "";
      row.append(image);
    } else {
      const placeholder = document.createElement("div");
      placeholder.className = "look-placeholder";
      placeholder.textContent = "+";
      row.append(placeholder);
    }
    const copy = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = item ? item.name : `SELECT ${category.slice(0, -1)}`;
    const label = document.createElement("small");
    label.textContent = category;
    copy.append(title, label);
    row.append(copy);
    if (item) {
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "✕";
      remove.setAttribute("aria-label", `Remove ${item.name} from look`);
      remove.addEventListener("click", () => {
        delete state.look[category];
        writeStorage("wardrobe-archive-look", state.look);
        renderLook();
        renderCounts();
      });
      row.append(remove);
    }
    slots.append(row);
  }
  const list = $("#saved-list");
  list.replaceChildren();
  for (let index = state.savedLooks.length - 1; index >= 0; index--) {
    const saved = state.savedLooks[index];
    const row = document.createElement("div");
    row.className = "saved-entry";
    const title = document.createElement("span");
    title.textContent = `LOOK ${formatCount(index + 1)} / ${saved.date}`;
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = "LOAD ↗";
    button.addEventListener("click", () => {
      state.look = { ...saved.items };
      writeStorage("wardrobe-archive-look", state.look);
      renderLook();
      renderCounts();
      notify("LOOK LOADED");
    });
    row.append(title, button);
    list.append(row);
  }
  renderCounts();
}

function openUpload() {
  $("#upload-dialog").showModal();
  $("#item-name").focus();
}
function resetUpload() {
  $("#upload-form").reset();
  state.selectedFile = null;
  if (state.previewUrl) URL.revokeObjectURL(state.previewUrl);
  state.previewUrl = null;
  $("#upload-preview").hidden = true;
  $("#upload-preview").removeAttribute("src");
  $("#dropzone-copy").hidden = false;
}
function setFile(file) {
  if (!file || !file.type.startsWith("image/")) {
    notify("CHOOSE AN IMAGE FILE");
    return;
  }
  state.selectedFile = file;
  if (state.previewUrl) URL.revokeObjectURL(state.previewUrl);
  state.previewUrl = URL.createObjectURL(file);
  $("#upload-preview").src = state.previewUrl;
  $("#upload-preview").hidden = false;
  $("#dropzone-copy").hidden = true;
}

function openDatabase() {
  return new Promise((resolve, reject) => {
    if (!window.indexedDB) return reject(new Error("IndexedDB unavailable"));
    const request = indexedDB.open("wardrobe-archive", 1);
    request.onupgradeneeded = () => request.result.createObjectStore("items", { keyPath: "id" });
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}
async function getUploads() {
  const database = await openDatabase();
  return new Promise((resolve, reject) => {
    const transaction = database.transaction("items", "readonly");
    const request = transaction.objectStore("items").getAll();
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
    transaction.oncomplete = () => database.close();
  });
}
async function saveUpload(item) {
  const database = await openDatabase();
  return new Promise((resolve, reject) => {
    const transaction = database.transaction("items", "readwrite");
    transaction.objectStore("items").put(item);
    transaction.oncomplete = () => { database.close(); resolve(); };
    transaction.onerror = () => reject(transaction.error);
  });
}
async function removeUpload(id) {
  const database = await openDatabase();
  return new Promise((resolve, reject) => {
    const transaction = database.transaction("items", "readwrite");
    transaction.objectStore("items").delete(id);
    transaction.oncomplete = () => { database.close(); resolve(); };
    transaction.onerror = () => reject(transaction.error);
  });
}

function renderStatus(message) {
  $("#render-status").textContent = message;
}

function getSegmenter() {
  if (!segmenterPromise) {
    segmenterPromise = import("https://cdn.jsdelivr.net/npm/@huggingface/transformers@3.8.1")
      .then(({ pipeline }) => pipeline("background-removal", "onnx-community/ormbg-ONNX", { dtype: "q8" }))
      .catch((error) => {
        segmenterPromise = null;
        throw error;
      });
  }
  return segmenterPromise;
}

function placeOnCatalogCanvas(source, box) {
  const canvas = document.createElement("canvas");
  canvas.width = 900;
  canvas.height = 900;
  const scale = Math.min(760 / box.width, 760 / box.height);
  const width = box.width * scale;
  const height = box.height * scale;
  canvas.getContext("2d").drawImage(
    source, box.x, box.y, box.width, box.height,
    (900 - width) / 2, (900 - height) / 2, width, height
  );
  return canvas.toDataURL("image/png");
}

function frameCutout(sourceCanvas, maskCanvas, useAlpha) {
  const width = sourceCanvas.width;
  const height = sourceCanvas.height;
  const sourcePixels = sourceCanvas.getContext("2d").getImageData(0, 0, width, height);
  const maskLayer = document.createElement("canvas");
  maskLayer.width = width;
  maskLayer.height = height;
  const maskContext = maskLayer.getContext("2d");
  maskContext.drawImage(maskCanvas, 0, 0, width, height);
  const maskPixels = maskContext.getImageData(0, 0, width, height).data;
  const pixels = sourcePixels.data;
  let minX = width, minY = height, maxX = 0, maxY = 0, count = 0;

  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const offset = (y * width + x) * 4;
      const confidence = maskPixels[offset + (useAlpha ? 3 : 0)];
      const alpha = Math.max(0, Math.min(255, Math.round((confidence - 24) * 1.22)));
      pixels[offset + 3] = Math.round(pixels[offset + 3] * alpha / 255);
      if (alpha > 75) {
        minX = Math.min(minX, x);
        minY = Math.min(minY, y);
        maxX = Math.max(maxX, x);
        maxY = Math.max(maxY, y);
        count++;
      }
    }
  }
  if (count < width * height * 0.01) {
    throw new Error("TRY A PHOTO WITH THE ENTIRE PIECE ON A CONTRASTING SURFACE");
  }
  const cutout = document.createElement("canvas");
  cutout.width = width;
  cutout.height = height;
  cutout.getContext("2d").putImageData(sourcePixels, 0, 0);
  return placeOnCatalogCanvas(cutout, {
    x: minX, y: minY, width: maxX - minX + 1, height: maxY - minY + 1
  });
}

async function processImage(file) {
  const bitmap = await createImageBitmap(file);
  const originalCanvas = document.createElement("canvas");
  const ratio = Math.min(1200 / Math.max(bitmap.width, bitmap.height), 1);
  originalCanvas.width = Math.round(bitmap.width * ratio);
  originalCanvas.height = Math.round(bitmap.height * ratio);
  originalCanvas.getContext("2d").drawImage(bitmap, 0, 0, originalCanvas.width, originalCanvas.height);
  const originalContext = originalCanvas.getContext("2d");
  const corners = [
    [0, 0], [originalCanvas.width - 1, 0],
    [0, originalCanvas.height - 1], [originalCanvas.width - 1, originalCanvas.height - 1]
  ];
  const transparent = corners.some(([x, y]) => originalContext.getImageData(x, y, 1, 1).data[3] < 16);
  const original = transparent ? originalCanvas.toDataURL("image/png") : originalCanvas.toDataURL("image/jpeg", 0.84);
  bitmap.close();
  if (transparent) {
    const { width, height } = originalCanvas;
    const pixels = originalContext.getImageData(0, 0, width, height).data;
    let minX = width, minY = height, maxX = 0, maxY = 0;
    for (let y = 0; y < height; y++) {
      for (let x = 0; x < width; x++) {
        if (pixels[(y * width + x) * 4 + 3] < 50) continue;
        minX = Math.min(minX, x);
        minY = Math.min(minY, y);
        maxX = Math.max(maxX, x);
        maxY = Math.max(maxY, y);
      }
    }
    if (maxX < minX || maxY < minY) throw new Error("TRY A PHOTO WITH THE ENTIRE PIECE ON A CONTRASTING SURFACE");
    return {
      original,
      image: placeOnCatalogCanvas(originalCanvas, {
        x: minX, y: minY, width: maxX - minX + 1, height: maxY - minY + 1
      })
    };
  }
  renderStatus("LOADING BACKGROUND REMOVER / FIRST USE MAY TAKE A MINUTE");
  const segmenter = await getSegmenter();
  renderStatus("REMOVING BACKGROUND");
  const output = await segmenter([originalCanvas]);
  if (!output?.[0]) throw new Error("BACKGROUND REMOVAL FAILED");
  renderStatus("FRAMING CUTOUT");
  const maskCanvas = await output[0].toCanvas();
  return { original, image: frameCutout(originalCanvas, maskCanvas, output[0].channels === 4) };
}

async function initialize() {
  try {
    const uploads = await getUploads();
    state.items.push(...uploads.sort((a, b) => a.createdAt - b.createdAt));
  } catch {
    notify("LOCAL SAVING MAY BE UNAVAILABLE");
  }
  renderGrid();
  renderLook();
}

document.querySelectorAll(".filter").forEach((button) => {
  button.addEventListener("click", () => {
    state.filter = button.dataset.filter;
    document.querySelectorAll(".filter").forEach((other) => other.classList.toggle("active", other === button));
    renderGrid();
  });
});
$("#search").addEventListener("input", (event) => {
  state.query = event.target.value.trim().toLowerCase();
  renderGrid();
});
$("#open-upload").addEventListener("click", openUpload);
$("#close-upload").addEventListener("click", () => $("#upload-dialog").close());
$("#upload-dialog").addEventListener("close", resetUpload);
$("#file-input").addEventListener("change", (event) => setFile(event.target.files[0]));
const dropzone = $("#dropzone");
for (const name of ["dragenter", "dragover"]) dropzone.addEventListener(name, (event) => {
  event.preventDefault();
  dropzone.classList.add("drag-over");
});
for (const name of ["dragleave", "drop"]) dropzone.addEventListener(name, (event) => {
  event.preventDefault();
  dropzone.classList.remove("drag-over");
});
dropzone.addEventListener("drop", (event) => {
  const file = event.dataTransfer.files[0];
  if (file) {
    const transfer = new DataTransfer();
    transfer.items.add(file);
    $("#file-input").files = transfer.files;
    setFile(file);
  }
});
$("#upload-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = state.selectedFile ?? $("#file-input").files[0];
  if (!file) return notify("CHOOSE A PHOTO FIRST");
  const name = $("#item-name").value.trim();
  if (!name) return notify("NAME YOUR PIECE");
  const category = $("#item-category").value;
  const button = $("#save-item");
  button.disabled = true;
  button.textContent = "PROCESSING...";
  try {
    const images = await processImage(file);
    const item = {
      id: `WA-${Date.now()}`,
      code: `UP-${formatCount(state.items.filter((entry) => entry.uploaded).length + 1)}`,
      name,
      category,
      ...images,
      uploaded: true,
      createdAt: Date.now()
    };
    await saveUpload(item);
    state.items.push(item);
    document.dispatchEvent(new Event("wardrobe:changed"));
    state.filter = category;
    state.query = "";
    $("#search").value = "";
    document.querySelectorAll(".filter").forEach((filter) => filter.classList.toggle("active", filter.dataset.filter === category));
    renderGrid();
    $("#upload-dialog").close();
    openItem(item);
    notify("PIECE ADDED TO YOUR ARCHIVE");
  } catch (error) {
    console.error(error);
    notify(error.message?.startsWith("TRY A PHOTO") ? error.message : "BACKGROUND REMOVAL FAILED — CHECK CONNECTION");
  } finally {
    button.disabled = false;
    button.innerHTML = "REMOVE BACKGROUND &amp; SAVE <span>↗</span>";
    renderStatus("");
  }
});
$("#close-item").addEventListener("click", () => $("#item-dialog").close());
$("#toggle-view").addEventListener("click", () => {
  if (!state.currentItem) return;
  state.originalView = !state.originalView;
  $("#detail-image").src = state.originalView ? state.currentItem.original : state.currentItem.image;
  $("#toggle-view").textContent = state.originalView ? "VIEW RENDER ↗" : "VIEW ORIGINAL ↗";
});
$("#add-to-look").addEventListener("click", () => {
  const item = state.currentItem;
  if (!item) return;
  state.look[item.category] = item.id;
  writeStorage("wardrobe-archive-look", state.look);
  renderLook();
  $("#item-dialog").close();
  $("#look-dialog").showModal();
  notify("ADDED TO LOOK");
});
$("#delete-item").addEventListener("click", async () => {
  const item = state.currentItem;
  if (!item?.uploaded || !confirm(`Remove "${item.name}" from this browser's archive?`)) return;
  try {
    await removeUpload(item.id);
    state.items = state.items.filter((entry) => entry.id !== item.id);
    document.dispatchEvent(new Event("wardrobe:changed"));
    if (state.look[item.category] === item.id) delete state.look[item.category];
    state.savedLooks = state.savedLooks.filter((look) => !Object.values(look.items).includes(item.id));
    writeStorage("wardrobe-archive-look", state.look);
    writeStorage("wardrobe-archive-saved-looks", state.savedLooks);
    renderGrid();
    renderLook();
    $("#item-dialog").close();
    notify("PIECE REMOVED");
  } catch {
    notify("COULD NOT REMOVE THIS PIECE");
  }
});
$("#open-look").addEventListener("click", () => { renderLook(); $("#look-dialog").showModal(); });
$("#close-look").addEventListener("click", () => $("#look-dialog").close());
$("#clear-look").addEventListener("click", () => {
  state.look = {};
  writeStorage("wardrobe-archive-look", state.look);
  renderLook();
  notify("LOOK CLEARED");
});
$("#save-look").addEventListener("click", () => {
  if (!categories.every((category) => findItem(state.look[category]))) return notify("SELECT A SHIRT, PANTS, AND SHOES");
  state.savedLooks.push({
    date: new Date().toLocaleDateString("en-US", { month: "short", day: "2-digit" }).toUpperCase(),
    items: { ...state.look }
  });
  writeStorage("wardrobe-archive-saved-looks", state.savedLooks);
  renderLook();
  notify("LOOK SAVED");
});
for (const dialog of document.querySelectorAll("dialog")) {
  dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
}
window.WardrobeArchive = {
  items: () => [...state.items],
  openItem
};

initialize();
