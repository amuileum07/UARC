import type { DesignReport, RocketDesign } from "./types";
export interface PreviewPart {
  id: string;
  name: string;
  profile: number[][];
  type: "body" | "fin" | "internal";
  thickness: number;
  count: number;
  cant: number;
  station: number;
  radius: number;
}

export function previewParts(
  design: RocketDesign,
  report: DesignReport,
): PreviewPart[] {
  return report.components.map((properties) => {
    const component = design.components.find((c) => c.id === properties.id);
    if (!component)
      throw new Error("Preview does not match the selected design.");
    const surface = "surface" in component ? component.surface : null;
    const fin = surface && "n" in surface;
    if (
      properties.outline_z_radius_m.some(
        (p) => p.length !== 2 || !p.every(Number.isFinite),
      )
    )
      throw new Error("Invalid preview geometry.");
    return {
      id: component.id,
      name: component.name || component.id,
      profile: properties.outline_z_radius_m,
      type: fin
        ? "fin"
        : "mass" in component || "packed_radius" in component
          ? "internal"
          : "body",
      thickness: "thickness" in component ? component.thickness : 0,
      count: fin ? surface.n : 1,
      cant: fin ? surface.cant_angle || 0 : 0,
      station:
        surface && typeof surface.position === "number" ? surface.position : 0,
      radius: surface?.rocket_radius || 0,
    };
  });
}
export function finVertices(
  part: PreviewPart,
  outline: number[][],
  copy: number,
): number[][] {
  const angle = (copy * Math.PI * 2) / part.count;
  const cant = (part.cant * Math.PI) / 180;
  return outline.map(([r, z]) => {
    const radial = part.radius + r;
    const tangent = z * Math.sin(cant);
    return [
      radial * Math.cos(angle) + tangent * Math.sin(angle),
      part.station + z * Math.cos(cant),
      -radial * Math.sin(angle) + tangent * Math.cos(angle),
    ];
  });
}
