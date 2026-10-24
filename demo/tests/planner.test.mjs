import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { ConverseCommand } from "@aws-sdk/client-bedrock-runtime";
import sharp from "sharp";
import { createApp, createWeeklyPlan } from "../server.mjs";

const days = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"];
const image = (await sharp({
  create: { width: 24, height: 24, channels: 3, background: "#dedede" }
}).jpeg().toBuffer()).toString("base64");
const items = [
  { id: "WA-001", name: "White tee", category: "shirts", image },
  { id: "WA-002", name: "Blue jeans", category: "pants", image },
  { id: "WA-003", name: "Black shoes", category: "shoes", image }
];
const nineItems = Array.from({ length: 9 }, (_, index) => ({
  ...items[index % 3],
  id: `WA-${String(index + 1).padStart(3, "0")}`,
  name: index < 3 ? items[index].name : `Piece ${index + 1}`
}));
const modelDays = days.map((day) => ({
  day, shirt: "WA-001", pants: "WA-002", shoes: "WA-003", note: "Simple colors."
}));
const fakeClient = (response, inspect = () => {}) => (key, region) => {
  assert.equal(key, "test-key");
  assert.equal(region, "us-east-1");
  return {
    chat: {
      completions: {
        create: async (request) => {
          await inspect(request);
          return response;
        }
      }
    }
  };
};

test("Bedrock Gemma 3 receives wardrobe images and returns seven valid outfits", async () => {
  let called = false;
  const result = await createWeeklyPlan(nineItems, "test-key", fakeClient(
    { choices: [{ message: { content: JSON.stringify({ days: modelDays }) } }] },
    async (request) => {
      called = true;
      assert.equal(request.model, "google.gemma-3-12b-it");
      const content = request.messages[0].content;
      const boards = content.filter((part) => part.type === "image_url");
      assert.equal(boards.length, 3);
      for (const board of boards) {
        assert.match(board.image_url.url, /^data:image\/jpeg;base64,/);
        const data = Buffer.from(board.image_url.url.split(",")[1], "base64");
        assert.equal((await sharp(data).metadata()).format, "jpeg");
      }
      assert.match(content.at(-1).text, /White tee/);
      assert.match(content.at(-1).text, /WA-009/);
    }
  ));
  assert.equal(called, true);
  assert.equal(result.length, 7);
  assert.deepEqual(result[0], modelDays[0]);
});

test("Gemma 3 cannot select an item outside the wardrobe", async () => {
  const invalid = modelDays.map((day) => ({ ...day }));
  invalid[0].shirt = "WA-999";
  await assert.rejects(
    createWeeklyPlan(items, "test-key", fakeClient({
      choices: [{ message: { content: JSON.stringify({ days: invalid }) } }]
    })),
    /outside your wardrobe/
  );
});

test("AWS credentials use the Bedrock Converse API with wardrobe images", async () => {
  let called = false;
  const plan = await createWeeklyPlan(
    nineItems,
    "",
    () => { throw new Error("API key client should not be used"); },
    "us-east-1",
    (region) => ({
      send: async (command) => {
        called = true;
        assert.equal(region, "us-east-1");
        assert.ok(command instanceof ConverseCommand);
        assert.equal(command.input.modelId, "google.gemma-3-12b-it");
        const content = command.input.messages[0].content;
        const boards = content.filter((part) => part.image);
        assert.equal(boards.length, 3);
        for (const board of boards) {
          assert.equal(board.image.format, "jpeg");
          assert.equal((await sharp(board.image.source.bytes).metadata()).format, "jpeg");
        }
        assert.match(content.at(-1).text, /WA-009/);
        return { output: { message: { content: [{ text: JSON.stringify({ days: modelDays }) }] } } };
      }
    })
  );
  assert.equal(called, true);
  assert.equal(plan.length, 7);
});

test("provider authentication errors identify the Bedrock API key", async () => {
  await assert.rejects(
    createWeeklyPlan(items, "test-key", () => ({
      chat: {
        completions: {
          create: async () => {
            const error = new Error("Unauthorized");
            error.status = 401;
            throw error;
          }
        }
      }
    })),
    /AWS_BEARER_TOKEN_BEDROCK/
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
  server = createApp({
    token: "",
    region: "us-east-1",
    awsClientFactory: () => ({
      config: {
        region: async () => "us-east-1",
        credentials: async () => { throw new Error("No credentials"); }
      }
    })
  });
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
  assert.deepEqual(await status.json(), { configured: false, model: "google.gemma-3-12b-it", region: "us-east-1" });
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

test("planner endpoint returns a full Gemma 3 week", async () => {
  const app = createApp({
    token: "test-key",
    clientFactory: fakeClient({
      choices: [{ message: { content: JSON.stringify({ days: modelDays }) } }]
    })
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

test("planner endpoint accepts configured AWS credentials without a bearer key", async () => {
  const app = createApp({
    token: "",
    region: "us-east-1",
    awsClientFactory: () => ({
      config: {
        region: async () => "us-east-1",
        credentials: async () => ({ accessKeyId: "test", secretAccessKey: "test" })
      },
      send: async () => ({
        output: { message: { content: [{ text: JSON.stringify({ days: modelDays }) }] } }
      })
    })
  });
  await new Promise((resolve) => app.listen(0, "127.0.0.1", resolve));
  try {
    const url = `http://127.0.0.1:${app.address().port}`;
    const status = await fetch(`${url}/api/status`);
    assert.deepEqual(await status.json(), { configured: true, model: "google.gemma-3-12b-it", region: "us-east-1" });
    const response = await fetch(`${url}/api/plan`, {
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
