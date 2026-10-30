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

test("usable WebGL 2 keeps multisampling and returns the original context", () => {
  const context = gpu();
  const attempts = install([context]);
  assert.equal(createWebGL2Canvas().context, context);
  assert.deepEqual(attempts, [{ antialias: true, alpha: true }]);
  assert.equal(context.released, false);
});

test("null shader precision and lost contexts retry once without MSAA", () => {
  for (const options of [{ invalidPrecision: true }, { lost: true }]) {
    const failed = gpu(options);
    const usable = gpu();
    const attempts = install([failed, usable]);
    assert.equal(createWebGL2Canvas().context, usable);
    assert.deepEqual(
      attempts.map((value) => value.antialias),
      [true, false],
    );
    assert.equal(failed.released, true);
    assert.equal(usable.released, false);
  }
});

test("two unusable contexts fail explicitly instead of inventing precision", () => {
  const failed = [gpu({ invalidPrecision: true }), gpu({ lost: true })];
  const attempts = install([...failed]);
  assert.throws(
    createWebGL2Canvas,
    /antialias=true:.*Shader precision unavailable.*antialias=false:.*lost/,
  );
  assert.equal(attempts.length, 2);
  assert.ok(failed.every((context) => context.released));
});

test("absent WebGL 2 fails after the same bounded attempts", () => {
  const attempts = install([null, null]);
  assert.throws(createWebGL2Canvas, /WebGL 2 is unavailable/);
  assert.equal(attempts.length, 2);
});
