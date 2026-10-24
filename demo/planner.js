const plannerDays = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"];
const plannerCategories = ["shirts", "pants", "shoes"];
const plannerStorageKey = "wardrobe-archive-weekly-plan";
const plannerApiBase = location.protocol === "http:"
  && ["localhost", "127.0.0.1"].includes(location.hostname)
  && location.port !== "8000"
  ? "http://127.0.0.1:8000"
  : "";
const planner = {
  view: "wardrobe",
  plan: null,
  generating: false,
  checkedServer: false
};

function plannerItems() {
  return window.WardrobeArchive.items();
}

function nextMonday() {
  const date = new Date();
  date.setHours(12, 0, 0, 0);
  const daysAhead = (8 - date.getDay()) % 7;
  date.setDate(date.getDate() + daysAhead);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function dateForDay(weekStart, index) {
  const date = new Date(`${weekStart}T12:00:00`);
  date.setDate(date.getDate() + index);
  return date.toLocaleDateString("en-US", { month: "short", day: "2-digit" }).toUpperCase();
}

function samplePlan(items, weekStart) {
  const groups = Object.fromEntries(plannerCategories.map((category) => [
    category, items.filter((item) => item.category === category)
  ]));
  return {
    source: "sample",
    weekStart,
    days: plannerDays.map((day, index) => ({
      day,
      shirt: groups.shirts[(index + Math.floor(index / 3)) % groups.shirts.length]?.id,
      pants: groups.pants[(index * 2 + 1) % groups.pants.length]?.id,
      shoes: groups.shoes[(index + 1) % groups.shoes.length]?.id,
      note: "A starting point from your wardrobe."
    }))
  };
}

function loadStoredPlan(weekStart) {
  try {
    const saved = JSON.parse(localStorage.getItem(plannerStorageKey));
    if (saved?.weekStart !== weekStart || saved?.source !== "gemma4" || saved.days?.length !== 7) return null;
    const items = plannerItems();
    if (saved.days.some((day) => plannerCategories.some((category) => {
      const id = day[category === "shirts" ? "shirt" : category === "pants" ? "pants" : "shoes"];
      return !items.some((item) => item.id === id && item.category === category);
    }))) return null;
    return saved;
  } catch {
    return null;
  }
}

function setPlanStatus(message, error = false) {
  const status = document.querySelector("#plan-status");
  status.textContent = message;
  status.classList.toggle("error", error);
}

function makePlanItem(item, category) {
  const button = document.createElement("button");
  button.className = "plan-item";
  button.type = "button";
  button.setAttribute("aria-label", item ? `View ${item.name}` : `No ${category} available`);
  if (item) {
    const image = document.createElement("img");
    image.src = item.image;
    image.alt = item.name;
    image.loading = "lazy";
    const code = document.createElement("span");
    code.className = "plan-item-label";
    code.textContent = item.code || item.name;
    button.append(image, code);
    button.addEventListener("click", () => window.WardrobeArchive.openItem(item));
  } else {
    button.disabled = true;
    const label = document.createElement("span");
    label.className = "plan-item-label";
    label.textContent = `ADD ${category.toUpperCase()}`;
    button.append(label);
  }
  return button;
}

function renderPlan() {
  const items = plannerItems();
  const weekStart = nextMonday();
  if (!planner.plan || planner.plan.weekStart !== weekStart) {
    planner.plan = loadStoredPlan(weekStart) || samplePlan(items, weekStart);
  }
  const source = document.querySelector("#plan-source");
  source.textContent = planner.plan.source === "gemma4" ? "GEMMA 4 / GENERATED" : "SAMPLE PLAN";
  const grid = document.querySelector("#plan-grid");
  grid.replaceChildren();
  planner.plan.days.forEach((day, index) => {
    const column = document.createElement("section");
    column.className = "plan-day";
    column.setAttribute("aria-label", `${plannerDays[index]} outfit`);
    const head = document.createElement("div");
    head.className = "plan-day-head";
    const name = document.createElement("span");
    name.className = "plan-day-name";
    name.textContent = plannerDays[index];
    const date = document.createElement("span");
    date.className = "plan-day-date";
    date.textContent = dateForDay(weekStart, index);
    head.append(name, date);
    column.append(head);
    for (const [category, key] of [["shirts", "shirt"], ["pants", "pants"], ["shoes", "shoes"]]) {
      column.append(makePlanItem(items.find((item) => item.id === day[key] && item.category === category), category));
    }
    const note = document.createElement("div");
    note.className = "plan-day-note";
    note.textContent = day.note || "";
    column.append(note);
    grid.append(column);
  });
}

async function imageForPlanner(item) {
  const image = new Image();
  image.src = item.image;
  await image.decode();
  const canvas = document.createElement("canvas");
  canvas.width = 384;
  canvas.height = 384;
  const context = canvas.getContext("2d");
  context.fillStyle = "#ffffff";
  context.fillRect(0, 0, 384, 384);
  const scale = Math.min(384 / image.naturalWidth, 384 / image.naturalHeight);
  const width = image.naturalWidth * scale;
  const height = image.naturalHeight * scale;
  context.drawImage(image, (384 - width) / 2, (384 - height) / 2, width, height);
  return {
    id: item.id,
    name: item.name,
    category: item.category,
    image: canvas.toDataURL("image/jpeg", 0.76).split(",")[1]
  };
}

async function checkPlannerServer() {
  try {
    const response = await fetch(`${plannerApiBase}/api/status`);
    if (!response.ok) {
      setPlanStatus("Run npm run dev to connect the Gemma 4 planner.");
      return false;
    }
    const status = await response.json();
    if (!status.configured) {
      setPlanStatus("Set GEMINI_API_KEY and run npm run dev to generate with Gemma 4.");
      return false;
    }
    return true;
  } catch {
    setPlanStatus("Run npm run dev to connect the Gemma 4 planner.");
    return false;
  }
}

async function generatePlan() {
  if (planner.generating) return;
  const items = plannerItems();
  if (plannerCategories.some((category) => !items.some((item) => item.category === category))) {
    setPlanStatus("Add at least one shirt, pair of pants, and pair of shoes to generate a plan.", true);
    return;
  }
  if (items.length > 60) {
    setPlanStatus("The planner can consider up to 60 pieces at once.", true);
    return;
  }
  planner.generating = true;
  const button = document.querySelector("#generate-plan");
  button.disabled = true;
  button.textContent = "BUILDING YOUR WEEK...";
  setPlanStatus("Reviewing your wardrobe with Gemma 4...");
  try {
    if (!await checkPlannerServer()) return;
    const catalog = await Promise.all(items.map(imageForPlanner));
    const response = await fetch(`${plannerApiBase}/api/plan`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items: catalog })
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Gemma 4 could not make a plan.");
    planner.plan = { source: "gemma4", weekStart: nextMonday(), days: result.days };
    localStorage.setItem(plannerStorageKey, JSON.stringify(planner.plan));
    renderPlan();
    setPlanStatus("Your Gemma 4 plan is ready. Select a piece to see its wardrobe entry.");
  } catch (error) {
    console.error(error);
    setPlanStatus(error.message || "Could not generate a plan. Try again.", true);
  } finally {
    planner.generating = false;
    button.disabled = false;
    button.innerHTML = "GENERATE WITH GEMMA 4 <span>↗</span>";
  }
}

async function showView(view) {
  planner.view = view;
  const plan = view === "plan";
  document.querySelector("#wardrobe-view").hidden = plan;
  document.querySelector("#plan-view").hidden = !plan;
  document.querySelector("#wardrobe-tab").classList.toggle("active", !plan);
  document.querySelector("#plan-tab").classList.toggle("active", plan);
  document.querySelector("#wardrobe-tab").setAttribute("aria-selected", String(!plan));
  document.querySelector("#plan-tab").setAttribute("aria-selected", String(plan));
  if (plan) {
    renderPlan();
    if (!planner.checkedServer && planner.plan.source !== "gemma4") {
      planner.checkedServer = true;
      if (await checkPlannerServer()) await generatePlan();
    }
  }
}

document.querySelector("#wardrobe-tab").addEventListener("click", () => showView("wardrobe"));
document.querySelector("#plan-tab").addEventListener("click", () => showView("plan"));
document.querySelector("#generate-plan").addEventListener("click", generatePlan);
document.querySelector(".brand").addEventListener("click", (event) => {
  event.preventDefault();
  showView("wardrobe");
});
document.addEventListener("wardrobe:changed", () => {
  planner.plan = null;
  localStorage.removeItem(plannerStorageKey);
  if (planner.view === "plan") renderPlan();
});
