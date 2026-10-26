import type { RocketDesign } from "./types";

export function editDesign(
  design: RocketDesign,
  path: string[],
  value: unknown,
): RocketDesign {
  const updated = structuredClone(design);
  let parent: object = updated;
  for (const key of path.slice(0, -1)) {
    const next: unknown = Reflect.get(parent, key);
    if (!next || typeof next !== "object")
      throw new Error(`Invalid design field: ${path.join(".")}`);
    parent = next;
  }
  const key = path.at(-1);
  if (!key) throw new Error("A field path is required.");
  Reflect.set(parent, key, value);
  if (key === "kind") {
    Reflect.deleteProperty(parent, "haack_c");
    Reflect.deleteProperty(parent, "power");
    if (value === "haack") Reflect.set(parent, "haack_c", 0.1);
    if (value === "powerseries") Reflect.set(parent, "power", 0.5);
    if (value === "haack" || value === "powerseries")
      Reflect.set(parent, "bluffness", 0);
  }
  if (
    path[0] === "environment" &&
    ["latitude", "longitude", "datum"].includes(key)
  ) {
    updated.environment.terrain = null;
    updated.environment.terrain_mode = "flat";
  }
  return updated;
}
