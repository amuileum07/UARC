import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

let dispose;
afterEach(() => {
  dispose?.();
  dispose = undefined;
  delete globalThis.window;
  delete globalThis.HTMLElement;
});

async function setup() {
  globalThis.window = new EventTarget();
  globalThis.HTMLElement = class {};
  const diagnostics = await import(`./diagnostics.ts?test=${Math.random()}`);
  dispose = diagnostics.installErrorReporting();
  return diagnostics;
}
const drained = () => new Promise(setImmediate);

test("queues bounded startup errors and flushes on pywebviewready", async () => {
  const { reportFrontendError } = await setup();
  for (let index = 0; index < 30; index++)
    reportFrontendError(
      "react",
      new Error(`startup ${index}`),
      "React",
      "<App>",
    );
  const reports = [];
  window.pywebview = {
    api: {
      report_frontend_error: async (payload) =>
        reports.push(JSON.parse(payload)),
    },
  };
  window.dispatchEvent(new Event("pywebviewready"));
  await drained();
  assert.equal(reports.length, 20);
  assert.equal(reports[0].message, "startup 10");
  assert.equal(reports[19].component_stack, "<App>");
  assert.match(reports[0].stack, /diagnostics.test.mjs/);
});

test("captures global errors, unhandled rejections and context loss; removes hooks", async () => {
  await setup();
  const reports = [];
  window.pywebview = {
    api: {
      report_frontend_error: async (value) => reports.push(JSON.parse(value)),
    },
  };
  const error = Object.assign(new Event("error"), {
    message: "window failure",
    error: new Error("window failure"),
    filename: "frontend.js",
    lineno: 12,
    colno: 3,
  });
  window.dispatchEvent(error);
  window.dispatchEvent(
    Object.assign(new Event("unhandledrejection"), {
      reason: "promise failure",
    }),
  );
  window.dispatchEvent(new Event("webglcontextlost"));
  await drained();
  assert.deepEqual(
    reports.map((report) => report.kind),
    ["error", "unhandledrejection", "renderer"],
  );
  assert.equal(reports[0].source, "frontend.js:12:3");
  dispose();
  window.dispatchEvent(error);
  await drained();
  assert.equal(reports.length, 3);
});

test("broken IPC does not recurse or create an unhandled rejection", async () => {
  const { reportFrontendError } = await setup();
  let calls = 0;
  window.pywebview = {
    api: {
      report_frontend_error: async () => {
        calls++;
        throw Error("bridge unavailable");
      },
    },
  };
  reportFrontendError("error", "original error");
  await drained();
  assert.equal(calls, 1);
});

test("bounds UTF-8 and JSON escaping, and handles unprintable rejection reasons", async () => {
  const { reportFrontendError } = await setup();
  const reports = [];
  window.pywebview = {
    api: {
      report_frontend_error: async (payload) => {
        assert.ok(new TextEncoder().encode(payload).length <= 32_768);
        reports.push(JSON.parse(payload));
      },
    },
  };
  for (const value of ["🚀", "\u0000"]) {
    const error = new Error(value.repeat(100_000));
    error.stack = value.repeat(100_000);
    reportFrontendError(
      "react",
      error,
      value.repeat(10_000),
      value.repeat(10_000),
    );
  }
  reportFrontendError("unhandledrejection", {
    toString() {
      throw Error("unprintable");
    },
  });
  await drained();
  assert.equal(reports.length, 3);
  assert.equal(reports[2].message, "Unknown frontend error");
});
