import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { createApp, createWeeklyPlan } from "../server.mjs";

const days = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"];
const image = Buffer.concat([Buffer.from([0xff, 0xd8]), Buffer.alloc(198)]).toString("base64");
const items = [
  { id: "WA-001", name: "White tee", category: "shirts", image },
  { id: "WA-002", name: "Blue jeans", category: "pants", image },
  { id: "WA-003", name: "Black shoes", category: "shoes", image }
];
const modelDays = days.map((day) => ({
  day, shirt: "WA-001", pants: "WA-002", shoes: "WA-003", note: "Simple colors."
}));
const fakeClient = (response, inspect = () => {}) => (key) => {
  assert.equal(key, "test-key");
  return {
    models: {
      generateContent: async (request) => {
        inspect(request);
        return response;
      }
    }
  };
};

test("Gemma 4 receives wardrobe images and returns seven valid outfits", async () => {
  let called = false;
  const result = await createWeeklyPlan(items, "test-key", fakeClient(
    { text: JSON.stringify({ days: modelDays }) },
    (request) => {
    called = true;
      assert.equal(request.model, "gemma-4-26b-a4b-it");
      assert.equal(request.contents.parts.filter((part) => part.inlineData).length, 3);
      assert.match(request.contents.parts.at(-1).text, /White tee/);
      assert.equal(request.config.thinkingConfig.thinkingLevel, "MINIMAL");
    }
  ));
  assert.equal(called, true);
  assert.equal(result.length, 7);
  assert.deepEqual(result[0], modelDays[0]);
});

test("Gemma 4 cannot select an item outside the wardrobe", async () => {
  const invalid = modelDays.map((day) => ({ ...day }));
  invalid[0].shirt = "WA-999";
  await assert.rejects(
    createWeeklyPlan(items, "test-key", fakeClient({ text: JSON.stringify({ days: invalid }) })),
    /outside your wardrobe/
  );
});

test("DNS failures are reported separately from API key failures", async () => {
  await assert.rejects(
    createWeeklyPlan(items, "test-key", () => ({
      models: {
        generateContent: async () => {
          const error = new TypeError("fetch failed");
          error.cause = { code: "ENOTFOUND" };
          throw error;
        }
      }
    })),
    /DNS lookup failed/
  );
});

test("planner requires all three categories", async () => {
  await assert.rejects(createWeeklyPlan(items.slice(0, 2), "test-key", () => {
    throw new Error("Should not call provider");
  }), /3 to 60 wardrobe pieces/);
});

let server;
let base;
before(async () => {
  server = createApp({ apiKey: "", clientFactory: () => { throw new Error("Should not call provider"); } });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  base = `http://127.0.0.1:${server.address().port}`;
});
after(() => new Promise((resolve) => server.close(resolve)));

test("local server serves both views and reports missing configuration", async () => {
  const page = await fetch(base);
  assert.equal(page.status, 200);
  const html = await page.text();
  assert.match(html, /id="plan-view"/);
  assert.match(html, /planner\.js/);
  const status = await fetch(`${base}/api/status`);
  assert.deepEqual(await status.json(), { configured: false, model: "gemma-4-26b-a4b-it" });
  const denied = await fetch(`${base}/api/plan`, { method: "POST" });
  assert.equal(denied.status, 503);
});

test("local preview on port 3000 can call the planner API on port 8000", async () => {
  const origin = "http://127.0.0.1:3000";
  const status = await fetch(`${base}/api/status`, { headers: { Origin: origin } });
  assert.equal(status.status, 200);
  assert.equal(status.headers.get("access-control-allow-origin"), origin);
  const preflight = await fetch(`${base}/api/plan`, {
    method: "OPTIONS",
    headers: { Origin: origin, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type" }
  });
  assert.equal(preflight.status, 204);
  assert.equal(preflight.headers.get("access-control-allow-origin"), origin);
  assert.match(preflight.headers.get("access-control-allow-headers"), /Content-Type/);
  const remote = await fetch(`${base}/api/status`, { headers: { Origin: "https://example.com" } });
  assert.equal(remote.status, 403);
});

test("planner endpoint returns a full Gemma week", async () => {
  const app = createApp({
    apiKey: "test-key",
    clientFactory: fakeClient({ text: JSON.stringify({ days: modelDays }) })
  });
  await new Promise((resolve) => app.listen(0, "127.0.0.1", resolve));
  try {
    const response = await fetch(`http://127.0.0.1:${app.address().port}/api/plan`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items })
    });
    assert.equal(response.status, 200);
    assert.deepEqual((await response.json()).days, modelDays);
  } finally {
    await new Promise((resolve) => app.close(resolve));
  }
});
