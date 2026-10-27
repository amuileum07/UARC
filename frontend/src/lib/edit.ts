import type { RocketDesign } from "./types";

export function componentRemovalIssue(
  design: RocketDesign,
  id: string,
): string {
  if (!design.components.some((component) => component.id === id))
    return "부품 목록에서 삭제할 항목을 선택하세요.";
  if (
    !design.components.some(
      (component) =>
        component.id !== id &&
        (component.component_type === "body_tube" ||
          component.component_type === "surface"),
    )
  )
    return "동체 또는 공력면이 하나 이상 필요합니다. 새 부품을 추가한 뒤 삭제하세요.";
  return "";
}

export function removeDesignComponent(
  design: RocketDesign,
  id: string,
): RocketDesign {
  if (componentRemovalIssue(design, id)) return design;
  return {
    ...design,
    components: design.components.filter((component) => component.id !== id),
  };
}

export function editDesign(
  design: RocketDesign,
  path: string[],
  value: unknown,
): RocketDesign {
  const updated = { ...design };
  let parent: object = updated;
  let original: object = design;
  for (const key of path.slice(0, -1)) {
    if (!Object.hasOwn(original, key))
      throw new Error(`Invalid design field: ${path.join(".")}`);
    const next: unknown = Reflect.get(original, key);
    if (!next || typeof next !== "object")
      throw new Error(`Invalid design field: ${path.join(".")}`);
    // Retain unrelated terrain/results references so scalar edits do not reload maps.
    const copy = Array.isArray(next) ? [...next] : { ...next };
    Reflect.set(parent, key, copy);
    original = next;
    parent = copy;
  }
  const key = path.at(-1);
  if (!key) throw new Error("A field path is required.");
  if (
    ["__proto__", "prototype", "constructor"].includes(key) &&
    !Object.hasOwn(parent, key)
  )
    throw new Error("Invalid design field.");
  const previous = Reflect.get(parent, key);
  Reflect.set(parent, key, value);
  if (key === "sweep_length" && value != null)
    Reflect.set(parent, "sweep_angle", null);
  if (key === "sweep_angle" && value != null)
    Reflect.set(parent, "sweep_length", null);
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
    ["latitude", "longitude", "datum"].includes(key) &&
    previous !== value
  ) {
    updated.environment.terrain = null;
    updated.environment.terrain_mode = "flat";
    updated.environment.geoid_undulation_m = null;
  }
  return updated;
}

export function placeLaunchSite(
  design: RocketDesign,
  latitude: number,
  longitude: number,
): RocketDesign {
  if (
    !Number.isFinite(latitude) ||
    !Number.isFinite(longitude) ||
    Math.abs(latitude) > 90 ||
    Math.abs(longitude) > 180
  )
    throw new Error("유효한 위도·경도를 선택하세요.");
  if (
    design.environment.datum === "WGS84" &&
    design.environment.latitude === latitude &&
    design.environment.longitude === longitude
  )
    return design;
  return {
    ...design,
    environment: {
      ...design.environment,
      latitude,
      longitude,
      datum: "WGS84",
      terrain: null,
      terrain_mode: "flat",
      geoid_undulation_m: null,
    },
  };
}
