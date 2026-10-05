import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { validateConfig } from "./bridge.ts";

afterEach(() => { delete globalThis.window; });

test("passes JSON arrays to the Python validator and returns its result", async () => {
  globalThis.window = new EventTarget();
  const input = { inertia: [0.08, 0.08, 0.002] };
  window.pywebview = { api: { validate_config: async (kind, payload) => {
    assert.equal(kind, "rocket");
    assert.deepEqual(JSON.parse(payload), input);
    return input;
  } } };
  assert.deepEqual(await validateConfig("rocket", input), input);
});

test("waits for pywebviewready when the page loads before the bridge", async () => {
  globalThis.window = new EventTarget();
  const result = validateConfig("environment", {});
  window.pywebview = { api: { validate_config: async () => ({ elevation: 120 }) } };
  window.dispatchEvent(new Event("pywebviewready"));
  assert.deepEqual(await result, { elevation: 120 });
});

test("propagates Python validation errors", async () => {
  globalThis.window = new EventTarget();
  window.pywebview = { api: { validate_config: async () => {
    throw new Error("Invalid radius");
  } } };
  await assert.rejects(validateConfig("rocket", {}), /Invalid radius/);
});

test("fails clearly when opened outside the desktop host", async (context) => {
  context.mock.timers.enable({ apis: ["setTimeout"] });
  globalThis.window = new EventTarget();
  const result = validateConfig("flight", {});
  context.mock.timers.tick(10_000);
  await assert.rejects(result, /UARC desktop window/);
});
