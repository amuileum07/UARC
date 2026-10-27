import type {
  MaterialConfig,
  RocketDesign,
  SurfaceFinishConfig,
} from "./types";

export interface MaterialPreset extends MaterialConfig {
  id: string;
  group: string;
  evidence: "software_reference" | "manufacturer_typical";
  source_ids: string[];
  notes: string;
}
export interface FinishPreset extends SurfaceFinishConfig {
  id: string;
  source_ids: string[];
  notes: string;
}
export interface MaterialCatalog {
  checked_on: string;
  materials: MaterialPreset[];
  surface_finishes: FinishPreset[];
  sources: Record<
    string,
    { title: string; url: string; locator: string; note: string }
  >;
  groups: Record<string, { name: string; notes: string; source_ids: string[] }>;
}
export const densityUnits = { bulk: "kg/m³", surface: "kg/m²", line: "kg/m" };
export const densityLabels = {
  bulk: "체적밀도",
  surface: "면밀도",
  line: "선밀도",
};

export function materialInUse(design: RocketDesign, id: string): boolean {
  return design.components.some(
    (c) =>
      ("material" in c && c.material === id) ||
      (c.component_type === "parachute" && c.line_material === id),
  );
}
export function compatibleMaterial(
  material: MaterialConfig,
  kind: RocketDesign["components"][number]["component_type"],
): boolean {
  const density = material.density_type || "bulk";
  if (kind === "line") return density === "line";
  if (kind === "parachute") return density === "bulk" || density === "surface";
  return kind !== "mass" && density === "bulk";
}
export function materialFromPreset(preset: MaterialPreset): MaterialConfig {
  return {
    name: preset.name,
    density: preset.density,
    density_type: preset.density_type,
    catalog_id: preset.id,
  };
}
export function finishFromPreset(preset: FinishPreset): SurfaceFinishConfig {
  return {
    name: preset.name,
    roughness_m: preset.roughness_m,
    roughness_type: preset.roughness_type,
    catalog_id: preset.id,
  };
}
