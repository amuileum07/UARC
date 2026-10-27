/** The subset of Pydantic JSON Schema used by the existing configuration DTOs. */
export interface InputSchema {
  $ref?: string;
  $defs?: Record<string, InputSchema>;
  type?: string;
  title?: string;
  description?: string;
  properties?: Record<string, InputSchema>;
  additionalProperties?: InputSchema | boolean;
  anyOf?: InputSchema[];
  oneOf?: InputSchema[];
  prefixItems?: InputSchema[];
  items?: InputSchema;
  minItems?: number;
  maxItems?: number;
  minimum?: number;
  exclusiveMinimum?: number;
  default?: unknown;
  const?: string | number | boolean;
  enum?: string[];
}
export function resolveSchema(
  schema: InputSchema,
  root: InputSchema,
): InputSchema {
  if (!schema.$ref) return schema;
  const name = schema.$ref.split("/").at(-1) || "";
  const resolved = root.$defs?.[name];
  if (!resolved) throw new Error(`설정 정의를 찾을 수 없습니다: ${name}`);
  return resolved;
}
export function variants(
  schema: InputSchema,
  root: InputSchema,
): InputSchema[] {
  const resolved = resolveSchema(schema, root);
  return (resolved.anyOf || resolved.oneOf || [resolved]).flatMap((branch) =>
    branch.anyOf || branch.oneOf
      ? variants(branch, root)
      : [resolveSchema(branch, root)],
  );
}
export function matchesSchema(value: unknown, schema: InputSchema): boolean {
  if (schema.const !== undefined) return value === schema.const;
  if (schema.type === "null") return value == null;
  if (schema.type === "array")
    return (
      Array.isArray(value) &&
      (!schema.minItems || value.length >= schema.minItems) &&
      (!schema.maxItems || value.length <= schema.maxItems)
    );
  if (schema.type === "object")
    return value !== null && typeof value === "object" && !Array.isArray(value);
  if (schema.type === "integer")
    return typeof value === "number" && Number.isInteger(value);
  return typeof value === schema.type;
}
export function seedValue(
  schema: InputSchema,
  root: InputSchema,
  key = "",
): unknown {
  const resolved = resolveSchema(schema, root);
  if (resolved.default !== undefined) return structuredClone(resolved.default);
  if (resolved.const !== undefined) return resolved.const;
  const branches = resolved.anyOf || resolved.oneOf;
  if (branches) return seedValue(branches[0], root, key);
  if (resolved.enum) return resolved.enum[0];
  if (resolved.type === "null") return null;
  if (resolved.type === "boolean") return false;
  if (resolved.type === "string") return "";
  if (resolved.type === "number" || resolved.type === "integer")
    return Math.max(
      resolved.minimum ?? 0,
      resolved.exclusiveMinimum === undefined
        ? 0
        : resolved.exclusiveMinimum + 1,
    );
  if (resolved.type === "array") {
    if (key === "initial_solution")
      return [0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0];
    if (key === "rtol" || key === "atol") return Array(13).fill(1e-6);
    const result =
      resolved.prefixItems?.map((item) => seedValue(item, root)) ||
      Array.from({ length: resolved.minItems || 2 }, () =>
        seedValue(resolved.items || {}, root),
      );
    if (result.every((item) => Array.isArray(item) && item.length === 2))
      return result.map((row, index) => [
        index,
        Array.isArray(row) ? row[1] : 0,
      ]);
    return result;
  }
  return Object.fromEntries(
    Object.entries(resolved.properties || {}).map(([name, item]) => [
      name,
      seedValue(item, root, name),
    ]),
  );
}
export function parseNumericTable(text: string): [number, number][] {
  const rows = text
    .trim()
    .split(/\r?\n/)
    .filter((line) => line.trim());
  if (rows.length < 2 || rows.length > 4096)
    throw new Error("표는 2~4096행이어야 합니다.");
  const points: [number, number][] = rows.map((line, i) => {
    const cells = line.trim().split(/[\s,;]+/);
    if (
      cells.length !== 2 ||
      cells.some((cell) => !Number.isFinite(Number(cell)))
    )
      throw new Error(`${i + 1}행: 두 개의 유효한 숫자가 필요합니다.`);
    return [Number(cells[0]), Number(cells[1])];
  });
  if (points.some((row, i) => i > 0 && row[0] <= points[i - 1][0]))
    throw new Error("첫 번째 열은 중복 없이 증가해야 합니다.");
  return points;
}
export const fieldLabels: Record<string, string> = {
  surface: "공력면",
  name: "이름",
  position: "위치",
  length: "길이",
  outer_radius: "바깥 반경",
  thickness: "두께",
  mass: "질량",
  radius: "반경",
  root_chord: "루트 코드",
  tip_chord: "팁 코드",
  span: "스팬",
  sweep_length: "후퇴 길이",
  sweep_angle: "후퇴각",
  cant_angle: "캔트각",
  n: "핀 개수",
  haack_c: "Haack C",
  rocket_radius: "기체 반경",
  base_radius: "밑면 반경",
  top_radius: "앞쪽 반경",
  bottom_radius: "뒤쪽 반경",
  power: "형상 지수",
  bluffness: "끝단 둔화 비율",
  kind: "노즈 형상",
  density: "밀도",
  material: "재질",
  mass_override: "실측 질량",
  inertia: "관성 텐서",
  center_of_mass: "질량중심",
  overrides: "실측 기체 값",
  packed_radius: "수납 반경",
  packed_length: "수납 길이",
  canopy_area: "원단 면적",
  attachment_position: "부착 위치",
  line_mass: "줄 질량",
  line_length: "줄 전체 길이",
  lag: "전개 지연",
  drag_coefficient: "항력 계수",
  deployment: "낙하산 전개",
  trigger: "전개 조건",
  cd_s: "실측 Cd·A",
  sampling_rate: "전개 판정 주파수",
  noise: "기압 센서 잡음",
  height: "높이",
  porosity: "기공률",
  inclination: "발사 경사각",
  heading: "방위각",
  rail_length: "레일 길이",
  max_time: "최대 계산 시간",
  max_time_step: "최대 시간 간격",
  min_time_step: "최소 시간 간격",
  initial_solution: "초기 비행 상태",
  terminate_on_apogee: "최고점에서 계산 종료",
  rtol: "상대 오차 허용값",
  atol: "절대 오차 허용값",
  time_overshoot: "이벤트 사이 계산 허용",
  verbose: "상세 계산 로그",
  equations_of_motion: "운동 방정식",
  ode_solver: "ODE 계산기",
  simulation_mode: "자유도",
  thrust_source: "추력",
  nozzle_radius: "노즐 반경",
  nozzle_position: "노즐 위치",
  dry_mass: "건조 질량",
  dry_inertia: "건조 관성 텐서",
  burn_time: "연소 시간",
  reshape_thrust_curve: "연소 시간·총 임펄스 재조정",
  interpolation_method: "곡선 보간",
  coordinate_system_orientation: "모터 좌표 방향",
  reference_pressure: "기준 기압",
  center_of_dry_mass_position: "건조 질량중심 위치",
  grain_number: "그레인 개수",
  grain_density: "그레인 밀도",
  grain_outer_radius: "그레인 바깥 반경",
  grain_initial_inner_radius: "그레인 초기 안쪽 반경",
  grain_initial_height: "그레인 초기 높이",
  grain_separation: "그레인 간격",
  grains_center_of_mass_position: "그레인 질량중심 위치",
  throat_radius: "목 반경",
  only_radial_burn: "반경 방향으로만 연소",
  chamber_radius: "연소실 반경",
  chamber_height: "연소실 높이",
  chamber_position: "연소실 위치",
  propellant_initial_mass: "초기 추진제 질량",
  motor_position: "모터 장착 위치",
  power_off_drag: "비추진 항력 계수",
  power_on_drag: "추진 중 항력 계수",
  rail_buttons: "레일 버튼",
  upper_button_position: "위쪽 버튼 위치",
  lower_button_position: "아래쪽 버튼 위치",
  angular_position: "버튼 각도",
  spherical_caps: "탱크 양 끝 구면 캡",
  flux_time: "유량 시간 범위",
  liquid: "액체",
  gas: "기체",
  liquid_mass: "액체 질량",
  gas_mass: "기체 질량",
  discretize: "탱크 계산 분할 수",
  gravity: "중력 가속도 직접 지정",
  max_expected_height: "대기 계산 상한 고도",
  pressure: "기압",
  temperature: "기온",
  wind_u: "동쪽 바람 u",
  wind_v: "북쪽 바람 v",
  atmosphere_file: "자료 파일 · 제공자",
  atmosphere_dictionary: "자료 변수 매핑",
  pressure_conversion_factor: "기압 단위 · 환산 계수",
  ensemble_member: "앙상블 멤버 번호",
};
export function fieldUnit(key: string) {
  if (key === "gravity") return "m/s²";
  if (key.includes("inertia")) return "kg·m²";
  if (key === "noise" || key === "pressure" || key === "reference_pressure")
    return "Pa";
  if (key === "temperature") return "K";
  if (key.startsWith("wind_")) return "m/s";
  if (key === "thrust_source") return "N";
  if (key === "density" || key.endsWith("_density")) return "kg/m³";
  if (key === "sampling_rate") return "Hz";
  if (key === "cd_s" || key === "canopy_area") return "m²";
  if (key === "mass_override" || /mass$/.test(key)) return "kg";
  if (/angle|inclination|heading/.test(key)) return "°";
  if (/time|lag/.test(key)) return "s";
  if (
    /radius|position|length|thickness|chord|span|height|separation|center_of_mass/.test(
      key,
    )
  )
    return "m";
  return "";
}
