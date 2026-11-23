import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync(new URL("../src/00-catalog-freshness.js", import.meta.url), "utf8");
const context = vm.createContext({ fetch: undefined });
vm.runInContext(source, context);
const { inspectCatalogFreshness, isCatalogRollback, loadCatalogSnapshot } = vm.runInContext(
  "({ inspectCatalogFreshness, isCatalogRollback, loadCatalogSnapshot })",
  context
);
const NOW = Date.parse("2026-11-23T12:00:00+03:00");
const freshBundle = { sync: { finished: "2026-11-22T13:00:00+03:00" } };
const staleBundle = { sync: { finished: "2026-09-30T14:05:58" } };

function response(status, data, etag = null) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: (name) => (name.toLowerCase() === "etag" ? etag : null) },
    json: async () => data,
  };
}

test("freshness accepts a recent timestamp and rejects stale or unknown timestamps", () => {
  assert.equal(inspectCatalogFreshness(freshBundle, NOW).status, "fresh");
  assert.equal(inspectCatalogFreshness(staleBundle, NOW).status, "stale");
  assert.equal(inspectCatalogFreshness({}, NOW).status, "unknown");
  assert.equal(
    inspectCatalogFreshness("2026-11-25T12:00:00+03:00", NOW).status,
    "unknown"
  );
});

test("a previously loaded catalog cannot be replaced by a lower revision or older sync", () => {
  const current = { revision: 12, sync: { finished: "2026-11-22T13:00:00+03:00" } };
  assert.equal(isCatalogRollback({ ...current, revision: 11 }, current), true);
  assert.equal(
    isCatalogRollback(
      { revision: 12, sync: { finished: "2026-11-21T13:00:00+03:00" } },
      current
    ),
    true
  );
  assert.equal(
    isCatalogRollback(
      { revision: 13, sync: { finished: "2026-11-23T10:00:00+03:00" } },
      current
    ),
    false
  );
  assert.equal(
    isCatalogRollback(
      { revision: 12, sync: { finished: "2026-11-22T13:00:00+03:00" } },
      current,
      'W/"cat-12-fin900-7-10"',
      'W/"cat-12-fin900-7-11"'
    ),
    true
  );
});

test("a fresh API bundle is preferred", async () => {
  const calls = [];
  const result = await loadCatalogSnapshot(async (url) => {
    calls.push(url);
    return response(200, freshBundle);
  });

  assert.equal(result.source, "api");
  assert.deepEqual(calls, ["/api/v1/bundle"]);
});

test("an unchanged ETag reuses the verified in-memory bundle without parsing JSON", async () => {
  const current = { sync: { finished: new Date(Date.now() - 60_000).toISOString() } };
  const result = await loadCatalogSnapshot(
    async () => ({
      ...response(200, null, 'W/"catalog-17"'),
      json: async () => {
        throw new Error("unchanged response should not be parsed");
      },
    }),
    'W/"catalog-17"',
    current
  );

  assert.equal(result.data, current);
  assert.equal(result.unchanged, true);
  assert.equal(result.source, "api");
});

test("a 304 without the matching in-memory ETag fails closed", async () => {
  await assert.rejects(
    loadCatalogSnapshot(
      async () => response(304, null, 'W/"catalog-18"'),
      'W/"catalog-17"',
      { sync: { finished: new Date(Date.now() - 60_000).toISOString() } }
    ),
    (error) => error.code === "CATALOG_VERSION_MISMATCH"
  );
});

test("a stale API bundle is rejected without substituting a static snapshot", async () => {
  const calls = [];
  await assert.rejects(
    loadCatalogSnapshot(async (url) => {
      calls.push(url);
      return response(200, staleBundle);
    }),
    (error) => error.code === "CATALOG_NOT_FRESH"
  );
  assert.deepEqual(calls, ["/api/v1/bundle"]);
});

test("a static host may use a fresh snapshot, but server errors do not trigger fallback", async () => {
  const calls = [];
  const result = await loadCatalogSnapshot(async (url) => {
    calls.push(url);
    return url === "/api/v1/bundle" ? response(404) : response(200, freshBundle);
  });
  assert.equal(result.source, "snapshot");
  assert.deepEqual(calls, ["/api/v1/bundle", "data.json"]);

  const failedCalls = [];
  await assert.rejects(
    loadCatalogSnapshot(async (url) => {
      failedCalls.push(url);
      return response(503);
    }),
    (error) => error.code === "CATALOG_API_ERROR"
  );
  assert.deepEqual(failedCalls, ["/api/v1/bundle"]);
});

test("a network failure can use only a cached snapshot inside the freshness window", async () => {
  const options = [];
  const result = await loadCatalogSnapshot(async (url, init) => {
    options.push([url, init?.cache]);
    if (url === "/api/v1/bundle") throw new TypeError("offline");
    return response(200, freshBundle);
  });
  assert.equal(result.source, "snapshot");
  assert.deepEqual(options, [
    ["/api/v1/bundle", "no-cache"],
    ["data.json", "force-cache"],
  ]);

  await assert.rejects(
    loadCatalogSnapshot(async (url) => {
      if (url === "/api/v1/bundle") throw new TypeError("offline");
      return response(200, staleBundle);
    }),
    (error) => error.code === "CATALOG_NOT_FRESH"
  );
});
