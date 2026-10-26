import assert from "node:assert/strict";
import { test } from "node:test";
import { previewQueue } from "./preview.ts";
import { editDesign } from "./edit.ts";
import { finVertices } from "./geometry.ts";
import { flightCoordinates } from "./geography.ts";

test("coalesces edits, serializes previews, discards late results, and disposes", async (context) => {
  context.mock.timers.enable({ apis: ["setTimeout"] });
  const calls = [],
    seen = [],
    errors = [];
  let resolve;
  const queue = previewQueue(
    (value) => {
      calls.push(value);
      return new Promise((done) => {
        resolve = done;
      });
    },
    (value) => seen.push(value),
    (error) => errors.push(error),
    10,
  );
  queue.push(1);
  queue.push(2);
  context.mock.timers.tick(10);
  assert.deepEqual(calls, [2]);
  queue.push(3);
  context.mock.timers.tick(10);
  assert.deepEqual(calls, [2]);
  resolve(2);
  await Promise.resolve();
  await Promise.resolve();
  context.mock.timers.tick(10);
  assert.deepEqual(seen, []);
  assert.deepEqual(calls, [2, 3]);
  resolve(3);
  await Promise.resolve();
  await Promise.resolve();
  assert.deepEqual(seen, [3]);
  queue.push(4);
  context.mock.timers.tick(10);
  queue.dispose();
  resolve(4);
  await Promise.resolve();
  assert.deepEqual(seen, [3]);
  assert.deepEqual(errors, []);
});
test("numeric edits retain the original, switch Haack fields, and invalidate old site data", () => {
  const original = {
    components: [{ surface: { kind: "haack", haack_c: 0.2 } }],
    environment: {
      latitude: 35,
      longitude: 129,
      terrain: { heights: [[1]] },
      terrain_mode: "terrain",
    },
  };
  const updated = editDesign(
    original,
    ["components", "0", "surface", "kind"],
    "powerseries",
  );
  assert.equal(original.components[0].surface.haack_c, 0.2);
  assert.equal(updated.components[0].surface.power, 0.5);
  assert.equal(updated.components[0].surface.haack_c, undefined);
  const moved = editDesign(original, ["environment", "latitude"], 36);
  assert.equal(moved.environment.terrain, null);
  assert.equal(moved.environment.terrain_mode, "flat");
});
test("fin view transforms preserve station and cant in both projections", () => {
  const part = { radius: 0.025, station: 0.12, count: 4, cant: 90 };
  const points = finVertices(
    part,
    [
      [0, 0],
      [0.08, -0.12],
    ],
    0,
  );
  assert.deepEqual(points[0], [0.025, 0.12, 0]);
  assert.ok(Math.abs(points[1][1] - 0.12) < 1e-12);
  assert.ok(Math.abs(points[1][2] + 0.12) < 1e-12);
});
test("map coordinates match the Python spherical reference", () => {
  assert.deepEqual(flightCoordinates(35, 129, 0, 0), [35, 129]);
  const [lat, lon] = flightCoordinates(35, 129, 100, 0);
  assert.ok(lon > 129);
  assert.ok(Math.abs(lat - 35) < 1e-6);
  assert.throws(() => flightCoordinates(0, 0, 10001, 0));
});
