import assert from "node:assert/strict";
import { test } from "node:test";
import {
  matchesSchema,
  parseNumericTable,
  resolveSchema,
  seedValue,
  variants,
  fieldUnit,
} from "./forms.ts";
import { createComponent, createMotor, createTank } from "./templates.ts";
import { editDesign } from "./edit.ts";

test("backend schema refs, nullable choices, fixed tuple variants and defaults remain distinct", () => {
  const root = {
    $defs: {
      Inertia: {
        anyOf: [
          {
            type: "array",
            minItems: 3,
            maxItems: 3,
            prefixItems: Array(3).fill({ type: "number" }),
          },
          {
            type: "array",
            minItems: 6,
            maxItems: 6,
            prefixItems: Array(6).fill({ type: "number" }),
          },
          { type: "null" },
        ],
      },
    },
  };
  const source = { $ref: "#/$defs/Inertia" };
  const choices = variants(source, root);
  assert.equal(choices.length, 3);
  assert.equal(matchesSchema([1, 1, 1], choices[0]), true);
  assert.equal(matchesSchema([1, 1, 1, 0, 0, 0], choices[0]), false);
  assert.equal(matchesSchema(null, choices[2]), true);
  assert.deepEqual(seedValue(choices[1], root), [0, 0, 0, 0, 0, 0]);
  assert.throws(() => resolveSchema({ $ref: "#/$defs/Absent" }, root));
  const original = { type: "array", default: [1, 2, 3] };
  const copied = seedValue(original, root);
  copied[0] = 99;
  assert.equal(original.default[0], 1);
  assert.equal(
    seedValue(
      { type: "array", minItems: 14, items: { type: "number" } },
      root,
      "initial_solution",
    )[7],
    1,
  );
  assert.deepEqual(
    seedValue(
      { type: "array", minItems: 13, items: { type: "number" } },
      root,
      "rtol",
    ),
    Array(13).fill(1e-6),
  );
});
test("curve tables accept numeric pasted data, reject malformed/nonfinite/duplicate/unordered coordinates", () => {
  assert.deepEqual(parseNumericTable("0, 2\n1\t3\n2; 4"), [
    [0, 2],
    [1, 3],
    [2, 4],
  ]);
  for (const text of [
    "",
    "0,1",
    "0,1\n0,2",
    "1,2\n0,3",
    "0,1\n1,NaN",
    "0,1\n1,2,3",
  ])
    assert.throws(() => parseNumericTable(text));
});
test("variant templates cover all serializable motors/surfaces and preserve common motor values", () => {
  const old = createMotor("generic", null);
  old.thrust_source = [
    [0, 0],
    [1, 50],
    [2, 0],
  ];
  for (const kind of ["generic", "solid", "liquid", "hybrid"]) {
    const motor = createMotor(kind, old);
    assert.equal(motor.motor_type, kind);
    assert.deepEqual(motor.thrust_source, old.thrust_source);
  }
  for (const kind of [
    "body_tube",
    "mass",
    "parachute",
    "nose",
    "tail",
    "trapezoidal_fins",
    "elliptical_fins",
  ]) {
    const part = createComponent(kind, "part", "stock");
    assert.equal(part.id, "part");
    if ("surface" in part) assert.equal(part.surface.surface_type, kind);
  }
  assert.equal(createTank().liquid_mass.length, 2);
  assert.equal(fieldUnit("dry_inertia"), "kg·m²");
  assert.equal(fieldUnit("mass_override"), "kg");
});
test("sweep alternatives update atomically, zero is meaningful, forbidden object paths cannot mutate prototypes", () => {
  const design = {
    components: [{ surface: { sweep_length: 0.1, sweep_angle: null } }],
  };
  const result = editDesign(
    design,
    ["components", "0", "surface", "sweep_angle"],
    0,
  );
  assert.equal(result.components[0].surface.sweep_length, null);
  assert.equal(result.components[0].surface.sweep_angle, 0);
  assert.equal(design.components[0].surface.sweep_length, 0.1);
  assert.throws(() => editDesign(design, ["__proto__", "polluted"], true));
  assert.equal({}.polluted, undefined);
  const material = JSON.parse('{"materials":{"constructor":{"density":1000}}}');
  assert.equal(
    editDesign(material, ["materials", "constructor", "density"], 1200)
      .materials.constructor.density,
    1200,
  );
});
