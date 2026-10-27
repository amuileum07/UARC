import type { MassBasedTankConfig, RocketDesign, SurfaceDesign } from "./types";
type Motor = NonNullable<RocketDesign["motor"]>;
export type MotorKind = NonNullable<Motor["motor_type"]>;
export const motorLabels = {
  generic: "일반 모터",
  solid: "고체 모터",
  liquid: "액체 모터",
  hybrid: "하이브리드 모터",
};
export const surfaceLabels = {
  nose: "노즈",
  trapezoidal_fins: "사다리꼴 핀",
  elliptical_fins: "타원형 핀",
  tail: "테일",
};
export function createMotor(
  kind: MotorKind,
  old: RocketDesign["motor"],
): Motor {
  const common = {
    thrust_source: old?.thrust_source ?? [
      [0, 0],
      [0.05, 60],
      [0.9, 60],
      [1, 0],
    ],
    nozzle_radius: old?.nozzle_radius ?? 0.01,
    dry_mass: old?.dry_mass ?? 0.15,
    dry_inertia:
      old?.dry_inertia ?? ([0.001, 0.001, 0.0001] as [number, number, number]),
    burn_time: old?.burn_time ?? 1,
    nozzle_position: old?.nozzle_position ?? 0,
    reshape_thrust_curve: old?.reshape_thrust_curve ?? false,
    interpolation_method: old?.interpolation_method ?? "linear",
    coordinate_system_orientation:
      old?.coordinate_system_orientation ?? "nozzle_to_combustion_chamber",
    reference_pressure: old?.reference_pressure ?? null,
    center_of_dry_mass_position: old?.center_of_dry_mass_position ?? 0.07,
  };
  if (kind === "generic")
    return {
      ...common,
      motor_type: kind,
      chamber_radius: 0.018,
      chamber_height: 0.12,
      chamber_position: 0.07,
      propellant_initial_mass: 0.1,
    };
  if (kind === "liquid") return { ...common, motor_type: kind };
  return {
    ...common,
    motor_type: kind,
    grain_number: 1,
    grain_density: 1800,
    grain_outer_radius: 0.018,
    grain_initial_inner_radius: 0.008,
    grain_initial_height: 0.05,
    grain_separation: 0,
    grains_center_of_mass_position: 0.07,
    throat_radius: 0.005,
    only_radial_burn: kind === "hybrid",
  };
}
export function createTank(): MassBasedTankConfig {
  return {
    name: "사용자 탱크",
    position: 0.15,
    radius: 0.02,
    height: 0.2,
    flux_time: 1,
    liquid: { name: "사용자 액체", density: 1000 },
    gas: { name: "사용자 기체", density: 1.2 },
    liquid_mass: [
      [0, 0.08],
      [1, 0.01],
    ],
    gas_mass: [
      [0, 0.0002],
      [1, 0.00028],
    ],
    spherical_caps: false,
    discretize: 100,
  };
}
export function createSurface(
  kind: keyof typeof surfaceLabels,
  radius = 0.025,
): SurfaceDesign["surface"] {
  const base = { position: 0.12, rocket_radius: radius };
  if (kind === "nose")
    return {
      ...base,
      position: 0.9,
      surface_type: kind,
      length: 0.2,
      kind: "conical",
      base_radius: radius,
    };
  if (kind === "tail")
    return {
      ...base,
      surface_type: kind,
      top_radius: radius,
      bottom_radius: radius * 0.8,
      length: 0.05,
    };
  if (kind === "elliptical_fins")
    return {
      ...base,
      surface_type: kind,
      n: 4,
      root_chord: 0.12,
      span: 0.08,
      cant_angle: 0,
    };
  return {
    ...base,
    surface_type: kind,
    n: 4,
    root_chord: 0.12,
    tip_chord: 0.05,
    span: 0.08,
    sweep_length: 0.035,
    cant_angle: 0,
  };
}
export type ComponentKind =
  | "body_tube"
  | "mass"
  | "line"
  | "parachute"
  | keyof typeof surfaceLabels;
export function createComponent(
  kind: ComponentKind,
  id: string,
  material: string,
  radius = 0.025,
): RocketDesign["components"][number] {
  if (kind === "body_tube")
    return {
      id,
      name: "동체",
      component_type: kind,
      material,
      position: 0,
      length: 0.6,
      outer_radius: radius,
      thickness: 0.001,
    };
  if (kind === "mass")
    return {
      id,
      name: "탑재 질량",
      component_type: kind,
      position: 0.4,
      mass: 0.1,
      radius: 0.015,
      length: 0.1,
    };
  if (kind === "line")
    return {
      id,
      name: "줄 · 웨빙",
      component_type: kind,
      material,
      position: 0.4,
      line_length: 1,
      packed_radius: 0.01,
      packed_length: 0.05,
    };
  if (kind === "parachute")
    return {
      id,
      name: "낙하산",
      component_type: kind,
      material,
      position: 0.5,
      attachment_position: 0.55,
      canopy_area: 0.3,
      thickness: 0.0001,
      line_mass: 0.01,
      packed_radius: 0.02,
      packed_length: 0.08,
      deployment: { name: "낙하산", radius: 0.3, trigger: "apogee", lag: 0.1 },
    };
  return {
    id,
    name: surfaceLabels[kind],
    component_type: "surface",
    material,
    thickness: 0.001,
    surface: createSurface(kind, radius),
  };
}
