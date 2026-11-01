import type { DesignReport, RocketDesign } from "./types";
import { fieldLabels } from "./forms.ts";
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

// Scene coordinates match finVertices: x is radial, y is rocket +z, z is tangent.
export type GuidePoint = [number, number, number];
export interface GeometryGuide {
  field: string;
  componentId: string | null;
  label: string;
  value: number;
  reference: string;
  origin: GuidePoint;
  from: GuidePoint;
  to: GuidePoint;
}
export function geometryGuide(
  design: RocketDesign,
  path: readonly string[] | null,
  report?: DesignReport,
): GeometryGuide | null {
  if (!path) return null;
  const key = path.at(-1) || "";
  let value: unknown;
  let componentId: string | null = null;
  let origin: GuidePoint = [0, 0, 0];
  let from: GuidePoint = [0, 0, 0];
  let to: GuidePoint = [0, 0, 0];
  let reference = "기체 원점 → 노즈 방향이 +z";
  if (path.length === 1 && key === "motor_position") {
    value = design.motor_position ?? 0;
    if (typeof value !== "number") return null;
    to = [0, value, 0];
    reference = "기체 원점 → 모터 장착 원점";
  } else if (
    (path.length === 2 &&
      path[0] === "overrides" &&
      key === "center_of_mass") ||
    (path.length === 2 &&
      path[0] === "rail_buttons" &&
      ["upper_button_position", "lower_button_position"].includes(key))
  ) {
    const object =
      path[0] === "overrides" ? design.overrides : design.rail_buttons;
    value = object && Reflect.get(object, key);
    if (typeof value !== "number") return null;
    to = [0, value, 0];
    reference = "기체 원점 기준의 축 방향 위치";
  } else if (
    path[0] === "components" &&
    (path.length === 3 || path.length === 4)
  ) {
    const component = design.components[Number(path[1])];
    if (!component) return null;
    componentId = component.id;
    const surface = "surface" in component ? component.surface : null;
    const nested = path.length === 4 && path[2] === "surface";
    if (path.length === 4 && !nested) return null;
    const object = nested ? surface : component;
    value = object && Reflect.get(object, key);
    if (typeof value !== "number") return null;
    const position = surface
      ? surface.position
      : Reflect.get(component, "position");
    if (typeof position !== "number") return null;
    const effectiveLength =
      surface && "length" in surface
        ? (report?.components.find((part) => part.id === component.id)
            ?.effective_length_m ?? surface.length)
        : 0;
    origin = [0, position, 0];
    from = [...origin];
    to = [...origin];
    if (key === "position" || key === "attachment_position") {
      origin = [0, 0, 0];
      from = [0, 0, 0];
      to = [0, value, 0];
      reference =
        key === "attachment_position"
          ? "기체 원점 → 낙하산 부착점"
          : surface?.surface_type === "nose"
            ? "기체 원점 → 노즈 끝"
            : surface?.surface_type === "tail"
              ? "기체 원점 → 테일 앞끝"
              : surface
                ? "기체 원점 → 핀 루트 앞전"
                : "outer_radius" in component
                  ? "기체 원점 → 동체 뒤끝"
                  : "기체 원점 → 부품 중심";
    } else if (surface && "n" in surface) {
      const cant = ((surface.cant_angle || 0) * Math.PI) / 180;
      const local = (
        radial: number,
        axial: number,
        tangent = 0,
      ): GuidePoint => [
        surface.rocket_radius + radial,
        position + axial * Math.cos(cant) - tangent * Math.sin(cant),
        axial * Math.sin(cant) + tangent * Math.cos(cant),
      ];
      const sweep =
        "tip_chord" in surface
          ? (surface.sweep_length ??
            (surface.sweep_angle != null
              ? surface.span * Math.tan((surface.sweep_angle * Math.PI) / 180)
              : surface.root_chord - surface.tip_chord))
          : surface.root_chord / 2;
      origin = local(0, 0);
      if (key === "root_chord") {
        from = local(0, 0);
        to = local(0, -value);
        reference = "핀 루트 앞전 → 루트 뒷전";
      } else if (key === "tip_chord") {
        from = local(surface.span, -sweep);
        to = local(surface.span, -sweep - value);
        reference = "핀 끝단 앞전 → 끝단 뒷전";
      } else if (key === "span") {
        from = local(0, -sweep);
        to = local(value, -sweep);
        reference = "장착 기체 표면 → 핀 끝단의 반경 방향 거리";
      } else if (key === "sweep_length") {
        from = local(0, 0);
        to = local(0, -value);
        reference = "핀 루트 앞전 기준의 끝단 앞전 후퇴 거리";
      } else if (key === "rocket_radius") {
        origin = [0, position, 0];
        from = [...origin];
        to = [value, position, 0];
        reference = "기체 중심축 → 핀 장착 표면";
      } else if (key === "thickness") {
        const middle =
          "tip_chord" in surface
            ? -(surface.root_chord + sweep + surface.tip_chord / 2) / 3
            : -surface.root_chord / 2;
        from = local(surface.span / 3, middle, -value / 2);
        to = local(surface.span / 3, middle, value / 2);
        reference = "핀 판의 양쪽 면 사이 두께";
      } else return null;
      reference = `첫 번째 핀 기준 · ${reference}`;
    } else if (key === "length" || key === "packed_length") {
      if (surface) {
        to = [0, position - value, 0];
        reference =
          surface.surface_type === "nose"
            ? "노즈 끝 → 밑면 · −z 방향"
            : "테일 앞끝 → 뒤끝 · −z 방향";
        if (surface.surface_type === "nose" && surface.bluffness)
          reference = "입력 명목 길이 · 둔화된 실제 형상 길이와 다를 수 있음";
      } else if ("outer_radius" in component) {
        to = [0, position + value, 0];
        reference = "동체 뒤끝 → 앞끝 · +z 방향";
      } else {
        from = [0, position - value / 2, 0];
        to = [0, position + value / 2, 0];
        reference = "부품 중심 기준으로 앞뒤에 길이의 절반씩";
      }
    } else if (
      [
        "outer_radius",
        "radius",
        "packed_radius",
        "base_radius",
        "rocket_radius",
        "top_radius",
        "bottom_radius",
      ].includes(key)
    ) {
      const axial =
        surface &&
        "length" in surface &&
        ["base_radius", "bottom_radius"].includes(key)
          ? position - effectiveLength
          : position;
      origin = [0, axial, 0];
      from = [...origin];
      to = [value, axial, 0];
      reference =
        key === "rocket_radius"
          ? "기체 중심축 → 기준 기체 반경"
          : "중심축 → 바깥 표면 · +r 방향";
    } else if (key === "thickness") {
      const radius =
        "outer_radius" in component
          ? component.outer_radius
          : surface?.surface_type === "nose"
            ? (surface.base_radius ?? surface.rocket_radius)
            : surface?.surface_type === "tail"
              ? surface.top_radius
              : null;
      if (radius === null) return null;
      const axial =
        surface?.surface_type === "nose"
          ? position - effectiveLength
          : position;
      origin = [0, axial, 0];
      from = [radius - value, axial, 0];
      to = [radius, axial, 0];
      reference = "안쪽 표면 → 바깥 표면 · 반경 방향 벽 두께";
    } else return null;
  } else return null;
  if (
    typeof value !== "number" ||
    !Number.isFinite(value) ||
    ![...origin, ...from, ...to].every(Number.isFinite)
  )
    return null;
  return {
    field: path.join("."),
    componentId,
    label: fieldLabels[key] || key,
    value,
    reference,
    origin,
    from,
    to,
  };
}
