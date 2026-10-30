import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { createWebGL2Canvas } from "./webgl.ts";

afterEach(() => {
  delete globalThis.document;
});

function gpu(options = {}) {
  return {
    VERTEX_SHADER: 0x8b31,
    FRAGMENT_SHADER: 0x8b30,
    HIGH_FLOAT: 0x8df2,
    released: false,
    isContextLost: () => options.lost || false,
    getShaderPrecisionFormat: () =>
      options.invalidPrecision ? null : { precision: 23 },
    getError: () => 0x0502,
    getExtension(name) {
      assert.equal(name, "WEBGL_lose_context");
      return {
        loseContext: () => {
          this.released = true;
        },
      };
    },
  };
}

function install(contexts) {
  const attempts = [];
  globalThis.document = {
    createElement(name) {
      assert.equal(name, "canvas");
      const context = contexts.shift();
      return {
        getContext(kind, attributes) {
          assert.equal(kind, "webgl2");
          attempts.push(attributes);
          return context;
        },
      };
    },
  };
  return attempts;
}

test("usable WebGL 2 never requests MSAA and returns the original context", () => {
  const context = gpu();
  const attempts = install([context]);
  assert.equal(createWebGL2Canvas().context, context);
  assert.deepEqual(attempts, [{ antialias: false, alpha: true }]);
  assert.equal(context.released, false);
});

test("null shader precision fails and releases the unusable context", () => {
  const failed = gpu({ invalidPrecision: true });
  const attempts = install([failed]);
  assert.throws(createWebGL2Canvas, /Shader precision unavailable/);
  assert.deepEqual(attempts, [{ antialias: false, alpha: true }]);
  assert.equal(failed.released, true);
});

test("lost contexts fail without retrying a faulted GPU", () => {
  const failed = gpu({ lost: true });
  const attempts = install([failed]);
  assert.throws(createWebGL2Canvas, /context was lost during creation/);
  assert.equal(attempts.length, 1);
  assert.equal(failed.released, true);
});

test("absent WebGL 2 fails explicitly without requesting MSAA", () => {
  const attempts = install([null]);
  assert.throws(createWebGL2Canvas, /WebGL 2 is unavailable/);
  assert.deepEqual(attempts, [{ antialias: false, alpha: true }]);
});
