import assert from "node:assert/strict";
import { test } from "node:test";
import { createGoogleLookup } from "../google-network.mjs";

function resolveLookup(lookup, hostname, options = {}) {
  return new Promise((resolve, reject) => {
    lookup(hostname, options, (error, address, family) => {
      if (error) reject(error);
      else resolve({ address, family });
    });
  });
}

test("Google API DNS uses the system resolver when it works", async () => {
  const lookup = createGoogleLookup(
    (hostname, options, callback) => callback(null, "192.0.2.1", 4),
    () => { throw new Error("Public DNS should not run"); }
  );
  assert.deepEqual(
    await resolveLookup(lookup, "generativelanguage.googleapis.com"),
    { address: "192.0.2.1", family: 4 }
  );
});

test("Google API DNS falls back to a public resolver after ENOTFOUND", async () => {
  const lookup = createGoogleLookup(
    (hostname, options, callback) => callback(Object.assign(new Error("Not found"), { code: "ENOTFOUND" })),
    async () => ["192.0.2.2", "192.0.2.3"]
  );
  assert.deepEqual(
    await resolveLookup(lookup, "generativelanguage.googleapis.com", { all: true }),
    {
      address: [
        { address: "192.0.2.2", family: 4 },
        { address: "192.0.2.3", family: 4 }
      ],
      family: undefined
    }
  );
});

test("Other hosts do not use the fallback resolver", async () => {
  const lookup = createGoogleLookup(
    (hostname, options, callback) => callback(Object.assign(new Error("Not found"), { code: "ENOTFOUND" })),
    () => { throw new Error("Public DNS should not run"); }
  );
  await assert.rejects(resolveLookup(lookup, "example.com"), /Not found/);
});
