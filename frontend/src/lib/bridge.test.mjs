import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import {
  getDesign,
  getDesignReport,
  previewDesign,
  rerunSimulation,
  submitDesign,
  validateConfig,
} from "./bridge.ts";

afterEach(() => {
  delete globalThis.window;
});

test("passes JSON arrays to the Python validator and returns its result", async () => {
  globalThis.window = new EventTarget();
  const input = { inertia: [0.08, 0.08, 0.002] };
  window.pywebview = {
    api: {
      validate_config: async (kind, payload) => {
        assert.equal(kind, "rocket");
        assert.deepEqual(JSON.parse(payload), input);
        return input;
      },
    },
  };
  assert.deepEqual(await validateConfig("rocket", input), input);
});

test("waits for pywebviewready when the page loads before the bridge", async () => {
  globalThis.window = new EventTarget();
  const result = validateConfig("environment", {});
  window.pywebview = {
    api: { validate_config: async () => ({ elevation: 120 }) },
  };
  window.dispatchEvent(new Event("pywebviewready"));
  assert.deepEqual(await result, { elevation: 120 });
});

test("propagates Python validation errors", async () => {
  globalThis.window = new EventTarget();
  window.pywebview = {
    api: {
      validate_config: async () => {
        throw new Error("Invalid radius");
      },
    },
  };
  await assert.rejects(validateConfig("rocket", {}), /Invalid radius/);
});

test("fails clearly when opened outside the desktop host", async (context) => {
  context.mock.timers.enable({ apis: ["setTimeout"] });
  globalThis.window = new EventTarget();
  const result = validateConfig("flight", {});
  context.mock.timers.tick(10_000);
  await assert.rejects(result, /UARC desktop window/);
});

test("transports numeric designs as JSON for preview and submission", async () => {
  for (const [method, call] of [
    ["preview_design", previewDesign],
    ["submit_design", submitDesign],
  ]) {
    globalThis.window = new EventTarget();
    const input = {
      materials: { stock: { density: 1200 } },
      components: [{ position: 0.4 }],
    };
    window.pywebview = {
      api: {
        [method]: async (payload) => {
          assert.deepEqual(JSON.parse(payload), input);
          return { mass_properties: { mass_kg: 1.2 } };
        },
      },
    };
    assert.deepEqual(await call(input), { mass_properties: { mass_kg: 1.2 } });
  }
});

test("loads saved designs and requests reruns by run ID", async () => {
  for (const [method, call] of [
    ["get_design", getDesign],
    ["get_design_report", getDesignReport],
    ["rerun", rerunSimulation],
  ]) {
    globalThis.window = new EventTarget();
    window.pywebview = {
      api: {
        [method]: async (runId) => {
          assert.equal(runId, "saved-run");
          return { name: "saved design" };
        },
      },
    };
    assert.deepEqual(await call("saved-run"), { name: "saved design" });
  }
});

test("waits when pywebview has created its API object but not registered methods", async () => {
  globalThis.window = new EventTarget();
  window.pywebview = { api: {} };
  const result = validateConfig("environment", {});
  window.pywebview.api.validate_config = async () => ({ elevation: 120 });
  window.dispatchEvent(new Event("pywebviewready"));
  assert.deepEqual(await result, { elevation: 120 });
});
