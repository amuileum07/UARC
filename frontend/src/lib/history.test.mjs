import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { setImmediate as turn } from "node:timers/promises";
import { watchHistory } from "./history.ts";

afterEach(() => delete globalThis.window);

test("idle history uses notifications, a slow recovery timer and focus recovery", async (context) => {
  context.mock.timers.enable({ apis: ["setTimeout"] });
  globalThis.window = new EventTarget();
  let calls = 0;
  const seen = [],
    errors = [];
  window.pywebview = {
    api: {
      list_runs: async () => {
        calls++;
        return [{ state: "succeeded" }];
      },
      list_designs: async () => [],
    },
  };
  const stop = watchHistory(
    (runs) => seen.push(runs),
    (error) => errors.push(error),
  );
  await turn();
  context.mock.timers.tick(29_999);
  await turn();
  assert.equal(calls, 1);
  window.dispatchEvent(new Event("uarc:history-changed"));
  await turn();
  assert.equal(calls, 2);
  context.mock.timers.tick(30_000);
  await turn();
  assert.equal(calls, 3);
  window.dispatchEvent(new Event("focus"));
  await turn();
  assert.equal(calls, 4);
  stop();
  window.dispatchEvent(new Event("uarc:history-changed"));
  context.mock.timers.tick(60_000);
  await turn();
  assert.equal(calls, 4);
  assert.equal(seen.length, 4);
  assert.deepEqual(errors, []);
});

test("notifications during an IPC read coalesce and cannot lose the final transition", async () => {
  globalThis.window = new EventTarget();
  const pending = [],
    seen = [];
  window.pywebview = {
    api: {
      list_runs: () => new Promise((resolve) => pending.push(resolve)),
      list_designs: async () => [],
    },
  };
  const stop = watchHistory((runs) => seen.push(runs), assert.fail);
  await turn();
  for (let index = 0; index < 20; index++)
    window.dispatchEvent(new Event("uarc:history-changed"));
  assert.equal(pending.length, 1);
  pending[0]([{ state: "running" }]);
  await turn();
  assert.equal(pending.length, 2);
  pending[1]([{ state: "succeeded" }]);
  await turn();
  assert.equal(pending.length, 2);
  assert.equal(seen.at(-1)[0].state, "succeeded");
  window.dispatchEvent(new Event("uarc:history-changed"));
  await turn();
  stop();
  pending[2]([{ state: "late reply after unmount" }]);
  await turn();
  assert.equal(seen.length, 2);
});

test("a failed history request remains retryable", async () => {
  globalThis.window = new EventTarget();
  let unavailable = true;
  const seen = [],
    errors = [];
  window.pywebview = {
    api: {
      list_runs: async () => {
        if (unavailable) throw Error("offline");
        return [];
      },
      list_designs: async () => [],
    },
  };
  const stop = watchHistory(
    (runs) => seen.push(runs),
    (error) => errors.push(error),
  );
  await turn();
  assert.match(String(errors[0]), /offline/);
  unavailable = false;
  window.dispatchEvent(new Event("focus"));
  await turn();
  assert.deepEqual(seen, [[]]);
  stop();
});
