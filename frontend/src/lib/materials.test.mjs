import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  compatibleMaterial,
  finishFromPreset,
  materialFromPreset,
  materialInUse,
} from "./materials.ts";

const catalog = JSON.parse(
  readFileSync(
    new URL("../../../backend/app/materials.json", import.meta.url),
    "utf8",
  ),
);

test("catalogue snapshots keep only portable density/roughness facts and provenance IDs", () => {
  const petg = catalog.materials.find((entry) => entry.id === "prusa_petg");
  assert.deepEqual(materialFromPreset(petg), {
    name: "PETG · Prusament",
    density: 1270,
    density_type: "bulk",
    catalog_id: petg.id,
  });
  assert.deepEqual(catalog.surface_finishes, []);
  const finish = {
    id: "user_measured",
    name: "Synthetic measured surface",
    roughness_m: 8e-6,
    roughness_type: "ra",
    source_ids: [],
    notes: "Verification input, not a material preset",
  };
  const saved = finishFromPreset(finish);
  assert.equal(saved.roughness_type, "ra");
  assert.equal(saved.roughness_m, 8e-6);
  saved.roughness_m = 0;
  assert.notEqual(finish.roughness_m, 0);
});

test("bulk/surface/line materials cannot be silently interchanged or deleted while used", () => {
  const bulk = { name: "Legacy", density: 1000 };
  const surface = { name: "Fabric", density: 0.083, density_type: "surface" };
  const line = { name: "Cord", density: 0.002, density_type: "line" };
  assert.equal(compatibleMaterial(bulk, "body_tube"), true);
  assert.equal(compatibleMaterial(surface, "parachute"), true);
  assert.equal(compatibleMaterial(line, "line"), true);
  assert.equal(compatibleMaterial(line, "body_tube"), false);
  assert.equal(compatibleMaterial(surface, "surface"), false);
  const design = {
    components: [
      {
        component_type: "parachute",
        material: "fabric",
        line_material: "cord",
      },
    ],
  };
  assert.equal(materialInUse(design, "cord"), true);
  assert.equal(materialInUse(design, "fabric"), true);
  assert.equal(materialInUse(design, "unused"), false);
});
