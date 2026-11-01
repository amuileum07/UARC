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
return {click, openPanel, painted, editPayloadMass}; })()`;

function browser(document, frame, overrides = {}) {
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
    ...overrides,
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

function jsonEditor(appliesInput = true) {
  const original = JSON.stringify(
    { components: [{ id: "payload", mass: 1 }] },
    null,
    2,
  );
  let draft = original;
  let applied = false;
  class Textarea {
    current = original;
    focused = false;
    get value() {
      return this.current;
    }
    set value(value) {
      this.current = value;
    }
    get defaultValue() {
      throw Error("defaultValue is not an edit acknowledgement");
    }
    focus() {
      this.focused = true;
    }
    dispatchEvent(event) {
      assert.equal(event.type, "input");
      assert.equal(this.focused, true);
      if (appliesInput) draft = this.value;
    }
  }
  const editor = new Textarea();
  const control = (label, click) => ({
    textContent: label,
    click,
    getClientRects: () => [1],
  });
  const menu = { open: false };
  const document = {
    querySelector: (selector) => (selector === ".view-menu" ? menu : editor),
    querySelectorAll: (selector) => {
      if (selector === '[role="tab"]')
        return [
          {
            getAttribute: (key) =>
              key === "aria-label" ? "설계 JSON" : "true",
          },
        ];
      if (selector === ".view-menu button")
        return [control("설계 JSON", () => {})];
      return [
        control("검증 후 적용", () => {
          // Validation commits later; the imperative DOM write must not pass first.
          setTimeout(() => {
            applied = true;
            editor.value = JSON.stringify(JSON.parse(draft), null, 2);
          }, 10);
        }),
      ];
    },
  };
  return { document, Textarea, editor, applied: () => applied };
}

test("JSON editing waits for the applied value without reading defaultValue", async () => {
  const fixture = jsonEditor();
  const api = await browser(fixture.document, undefined, {
    HTMLTextAreaElement: fixture.Textarea,
    Event,
  });
  await api.editPayloadMass();
  assert.equal(fixture.applied(), true);
  assert.equal(JSON.parse(fixture.editor.value).components[0].mass, 1.05);
});

test("an ignored input event cannot pass from the imperative textarea value alone", async () => {
  const fixture = jsonEditor(false);
  let time = 0;
  const api = await browser(fixture.document, undefined, {
    HTMLTextAreaElement: fixture.Textarea,
    Event,
    performance: { now: () => (time += 10000) },
  });
  await assert.rejects(api.editPayloadMass(), /Timed out: JSON edit applied/);
  assert.equal(JSON.parse(fixture.editor.value).components[0].mass, 1);
});
