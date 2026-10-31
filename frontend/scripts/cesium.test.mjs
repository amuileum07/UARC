import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import { pathToFileURL } from "node:url";
import { runInNewContext } from "node:vm";
import * as Cesium from "cesium";

// Execute the installed engine's actual calculation, including our pnpm patch.
const engine = createRequire(import.meta.resolve("cesium")).resolve(
  "@cesium/engine",
);
const source = readFileSync(
  new URL("./Source/Scene/QuadtreePrimitive.js", pathToFileURL(engine)),
  "utf8",
);
const screenSpaceError = runInNewContext(
  `(${source.slice(source.indexOf("function screenSpaceError("), source.indexOf("function screenSpaceError2D("))})`,
  {
    SceneMode: Cesium.SceneMode,
    OrthographicFrustum: Cesium.OrthographicFrustum,
    OrthographicOffCenterFrustum: Cesium.OrthographicOffCenterFrustum,
  },
);

test("Cesium zero-error terrain leaves remain terminal at zero camera distance", () => {
  const frame = {
    mode: Cesium.SceneMode.SCENE3D,
    camera: { frustum: { sseDenominator: 2 } },
    context: { drawingBufferHeight: 1000 },
    fog: { enabled: false },
    pixelRatio: 1,
  };
  for (const [geometricError, distance, expected] of [
    [0, 0, 0],
    [0, 10, 0],
    [2, 10, 100],
    [2, 0, Infinity],
  ]) {
    const primitive = {
      _tileProvider: { getLevelMaximumGeometricError: () => geometricError },
    };
    assert.equal(
      screenSpaceError(primitive, frame, { level: 18, _distance: distance }),
      expected,
    );
  }
});
