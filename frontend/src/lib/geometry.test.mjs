import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { geometryGuide } from "./geometry.ts";

const fixture = JSON.parse(
  readFileSync(
    new URL("../../../examples/design.json", import.meta.url),
    "utf8",
  ),
);
const at = (design, index, ...path) =>
  geometryGuide(design, ["components", String(index), ...path]);
const near = (actual, expected) =>
  assert.ok(Math.abs(actual - expected) < 1e-12, `${actual} != ${expected}`);
const distance = (guide) =>
  Math.hypot(...guide.to.map((value, index) => value - guide.from[index]));

test("position uses the global origin and retains signed axial coordinates", () => {
  const design = structuredClone(fixture);
  design.components[0].position = -0.15;
  const guide = at(design, 0, "position");
  assert.deepEqual(guide.origin, [0, 0, 0]);
  assert.deepEqual(guide.from, [0, 0, 0]);
  assert.deepEqual(guide.to, [0, -0.15, 0]);
  assert.match(guide.reference, /동체 뒤끝/);
  assert.deepEqual(at(design, 1, "surface", "position").to, [0, 0.8, 0]);
});

test("tube length extends forward while nose and tail length extend aft", () => {
  const design = structuredClone(fixture);
  const tube = at(design, 0, "length");
  assert.deepEqual(tube.from, [0, 0, 0]);
  assert.deepEqual(tube.to, [0, 0.6, 0]);
  const nose = at(design, 1, "surface", "length");
  near(nose.to[1], 0.6);
  near(nose.from[1], 0.8);
  design.components.push({
    id: "tail",
    component_type: "surface",
    thickness: 0.001,
    surface: {
      surface_type: "tail",
      position: 0.1,
      length: 0.05,
      rocket_radius: 0.025,
      top_radius: 0.025,
      bottom_radius: 0.02,
    },
  });
  const tail = at(design, 5, "surface", "length");
  near(tail.to[1], 0.05);
  assert.match(tail.reference, /−z/);
});

test("radii start at the axis and shell thickness spans the two wall surfaces", () => {
  assert.deepEqual(at(fixture, 0, "outer_radius").to, [0.025, 0, 0]);
  const wall = at(fixture, 0, "thickness");
  near(wall.from[0], 0.024);
  near(wall.to[0], 0.025);
  near(distance(wall), 0.001);
  near(at(fixture, 1, "surface", "base_radius").origin[1], 0.6);
});

test("packed and mass lengths are centered on their component CG", () => {
  for (const [index, key, length] of [
    [3, "length", 0.15],
    [4, "packed_length", 0.08],
  ]) {
    const guide = at(fixture, index, key);
    near((guide.from[1] + guide.to[1]) / 2, fixture.components[index].position);
    near(distance(guide), length);
  }
  assert.deepEqual(at(fixture, 4, "attachment_position").to, [0, 0.55, 0]);
  assert.deepEqual(at(fixture, 4, "packed_radius").to, [0.02, 0.5, 0]);
});

test("fin chord, span, tip and plate thickness share the rendered cant transform", () => {
  const design = structuredClone(fixture);
  design.components[2].surface.cant_angle = 30;
  const chord = at(design, 2, "surface", "root_chord");
  near(distance(chord), 0.12);
  near(chord.to[1], 0.12 - 0.12 * Math.cos(Math.PI / 6));
  near(chord.to[2], -0.12 * Math.sin(Math.PI / 6));
  near(distance(at(design, 2, "surface", "tip_chord")), 0.05);
  near(distance(at(design, 2, "surface", "span")), 0.08);
  const thickness = at(design, 2, "thickness");
  near(distance(thickness), 0.002);
  near(
    chord.to.reduce(
      (sum, value, i) =>
        sum + (value - chord.from[i]) * (thickness.to[i] - thickness.from[i]),
      0,
    ),
    0,
  );
});

test("elliptical fin span is measured at mid-chord; automatic sweep stays axial", () => {
  const design = structuredClone(fixture);
  design.components[2].surface = {
    surface_type: "elliptical_fins",
    position: 0.2,
    rocket_radius: 0.025,
    n: 3,
    root_chord: 0.12,
    span: 0.08,
  };
  const ellipse = at(design, 2, "surface", "span");
  near(ellipse.from[1], 0.14);
  near(ellipse.to[0], 0.105);
  const trapezoid = structuredClone(fixture);
  delete trapezoid.components[2].surface.sweep_length;
  const tip = at(trapezoid, 2, "surface", "tip_chord");
  near(tip.from[1], 0.12 - (0.12 - 0.05));
});

test("blunted nose base uses the solver's effective length and labels nominal input length", () => {
  const design = structuredClone(fixture);
  design.components[1].surface.bluffness = 0.1;
  const report = { components: [{ id: "nose", effective_length_m: 0.15 }] };
  const radius = geometryGuide(
    design,
    ["components", "1", "surface", "base_radius"],
    report,
  );
  near(radius.origin[1], 0.65);
  assert.match(at(design, 1, "surface", "length").reference, /명목 길이/);
});

test("assembly positions use the rocket datum while nonspatial and invalid values produce no guide", () => {
  const original = JSON.stringify(fixture);
  assert.deepEqual(
    geometryGuide(fixture, ["rail_buttons", "upper_button_position"]).to,
    [0, 0.2, 0],
  );
  assert.deepEqual(geometryGuide(fixture, ["motor_position"]).to, [0, 0, 0]);
  for (const path of [
    null,
    [],
    ["components", "99", "length"],
    ["components", "3", "mass"],
    ["components", "4", "deployment", "radius"],
    ["flight", "rail_length"],
    ["motor", "nozzle_radius"],
  ])
    assert.equal(geometryGuide(fixture, path), null);
  const invalid = structuredClone(fixture);
  invalid.components[0].length = Infinity;
  assert.equal(at(invalid, 0, "length"), null);
  invalid.components[0].position = NaN;
  assert.equal(at(invalid, 0, "position"), null);
  assert.equal(JSON.stringify(fixture), original);
});
