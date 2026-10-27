import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { componentRemovalIssue, removeDesignComponent } from "./edit.ts";

const example = JSON.parse(
  readFileSync(
    new URL("../../../examples/design.json", import.meta.url),
    "utf8",
  ),
);

test("deleting an added component preserves the original and unrelated inputs", () => {
  const added = {
    ...example,
    components: [
      ...example.components,
      { id: "added", component_type: "mass", mass: 0.1, position: 0.4 },
    ],
  };
  assert.equal(componentRemovalIssue(added, "added"), "");
  const removed = removeDesignComponent(added, "added");
  assert.deepEqual(removed.components, example.components);
  assert.equal(added.components.at(-1).id, "added");
  assert.equal(removed.environment, added.environment);
  assert.equal(removed.motor, added.motor);
  assert.equal(removed.materials, added.materials);
});

test("all component kinds can be removed while geometry remains", () => {
  for (const component of example.components) {
    assert.equal(componentRemovalIssue(example, component.id), "");
    assert.equal(
      removeDesignComponent(example, component.id).components.some(
        (part) => part.id === component.id,
      ),
      false,
    );
  }
});

test("last geometry and missing/special selections cannot invalidate a design", () => {
  const design = {
    ...example,
    components: example.components.filter(
      (part) => part.component_type !== "surface",
    ),
  };
  assert.match(componentRemovalIssue(design, "body"), /동체/);
  assert.equal(removeDesignComponent(design, "body"), design);
  assert.equal(componentRemovalIssue(design, "payload"), "");
  for (const id of ["missing", "assembly", "motor", "materials", "flight"]) {
    assert.ok(componentRemovalIssue(design, id));
    assert.equal(removeDesignComponent(design, id), design);
  }
  const onlyBody = { ...design, components: [design.components[0]] };
  assert.equal(removeDesignComponent(onlyBody, "body"), onlyBody);
});
