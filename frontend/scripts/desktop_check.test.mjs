import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { runInNewContext, Script } from "node:vm";

const source = readFileSync(
  new URL("../../backend/scripts/desktop_check.js", import.meta.url),
  "utf8",
);
new Script(source, { filename: "desktop_check.js" });
new Script(
  readFileSync(
    new URL("../../backend/scripts/probe_webgl.js", import.meta.url),
    "utf8",
  ),
  { filename: "probe_webgl.js" },
);
// Exercise the same action helpers used by the full native scenario.
const helpers = `${source.slice(0, source.indexOf("  let api;"))}
return {click, openPanel, painted}; })()`;

function browser(document, frame) {
  return runInNewContext(helpers, {
    document,
    window: { addEventListener() {} },
    performance,
    requestAnimationFrame: (callback) =>
      setTimeout(() => {
        frame?.();
        callback(performance.now());
      }, 0),
    setTimeout,
  });
}

test("UI actions wait for a rendered frame and React's subsequent commit task", async () => {
  let committed = false;
  const button = {
    textContent: "Apply",
    getClientRects: () => [1],
    click() {},
  };
  const api = await browser({ querySelectorAll: () => [button] }, () => {
    setTimeout(() => {
      committed = true;
    }, 0);
  });
  await api.click("apply", "button", "Apply");
  assert.equal(committed, true);
});

test("opening a panel waits for Dockview readiness and selected-tab state", async () => {
  let ready = false;
  let selected = false;
  let clicked = false;
  const menu = { open: false };
  const tab = {
    getAttribute: (key) => (key === "aria-label" ? "Design" : String(selected)),
  };
  const button = {
    textContent: "Design",
    getClientRects: () => [1],
    click() {
      assert.equal(ready, true);
      clicked = true;
      setTimeout(() => {
        selected = true;
      }, 0);
    },
  };
  const api = await browser({
    querySelector: () => menu,
    querySelectorAll: (selector) =>
      selector === '[role="tab"]' ? (ready ? [tab] : []) : [button],
  });
  const opened = api.openPanel("Design");
  await new Promise((resolve) => setTimeout(resolve, 10));
  assert.equal(clicked, false);
  ready = true;
  await opened;
  assert.equal(selected, true);
  assert.equal(menu.open, false);
});
