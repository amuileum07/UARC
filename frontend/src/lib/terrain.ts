import type { EnvironmentConfig, TerrainGrid, TerrainRequest } from "./types";

export const terrainReferences = {
  unknown: "미지정 · 검증 불가",
  EGM96: "EGM96 정표고",
  EGM2008: "EGM2008 정표고",
  national: "국가 수직 기준 · 원본 자료 기준",
  ellipsoid: "타원체고 h",
} as const;

export function alignLaunchElevation(
  env: EnvironmentConfig,
): EnvironmentConfig | null {
  const grid = env.terrain;
  const pad = env.pad_height_m ?? 0;
  if (
    env.datum !== "WGS84" ||
    !grid ||
    grid.reference === "unknown" ||
    !Number.isFinite(env.latitude) ||
    !Number.isFinite(env.longitude) ||
    !Number.isFinite(pad) ||
    pad < 0
  )
    return null;
  const ground = terrainHeight(grid, env.latitude, env.longitude);
  if (ground === null || !Number.isFinite(ground + pad)) return null;
  if (
    env.elevation === ground + pad &&
    env.elevation_reference === grid.reference
  )
    return env;
  return {
    ...env,
    elevation: ground + pad,
    elevation_reference: grid.reference,
    geoid_undulation_m:
      env.elevation_reference === grid.reference
        ? env.geoid_undulation_m
        : null,
  };
}

export function launchElevationIssue(env: EnvironmentConfig): string {
  if (env.elevation_mode !== "terrain") return "";
  if (env.datum !== "WGS84")
    return "발사 위치의 좌표 기준을 WGS84로 지정하세요.";
  if (!env.terrain)
    return "발사 고도를 자동 설정하려면 계산용 지형을 가져와야 합니다.";
  if (env.terrain.reference === "unknown")
    return "지형의 수직 고도 기준을 확인한 뒤 다시 가져오세요.";
  const aligned = alignLaunchElevation(env);
  if (!aligned)
    return "발사점의 지형 고도와 발사대 높이를 확인하세요. 범위 밖·결측 고도는 사용할 수 없습니다.";
  return aligned === env
    ? ""
    : "지형과 발사대 높이에 맞춰 발사 고도를 갱신하고 있습니다.";
}

export function defaultTerrainRequest(
  env: Pick<EnvironmentConfig, "latitude" | "longitude" | "datum" | "terrain">,
  radius = 1000,
  spacing = 30,
): TerrainRequest | null {
  if (
    env.terrain ||
    env.datum !== "WGS84" ||
    !Number.isFinite(env.latitude) ||
    !Number.isFinite(env.longitude) ||
    Math.abs(env.latitude) > 80 ||
    Math.abs(env.longitude) > 179.8 ||
    !Number.isFinite(radius) ||
    radius < 100 ||
    radius > 5000 ||
    !Number.isFinite(spacing) ||
    spacing < 5 ||
    spacing > 1000
  )
    return null;
  return {
    provider: "aws",
    latitude: env.latitude,
    longitude: env.longitude,
    radius_m: radius,
    spacing_m: spacing,
  };
}

export function terrainMatchesSite(
  env: EnvironmentConfig,
  area: TerrainRequest,
): boolean {
  return (
    env.datum === "WGS84" &&
    env.latitude === area.latitude &&
    env.longitude === area.longitude
  );
}

/** Display interpolation only; flight contact remains authoritative in Python. */
export function terrainHeight(
  grid: TerrainGrid,
  latitude: number,
  longitude: number,
): number | null {
  if (
    latitude < grid.south ||
    latitude > grid.north ||
    longitude < grid.west ||
    longitude > grid.east
  )
    return null;
  const rows = grid.heights.length,
    columns = grid.heights[0].length;
  const y = ((latitude - grid.south) / (grid.north - grid.south)) * (rows - 1);
  const x = ((longitude - grid.west) / (grid.east - grid.west)) * (columns - 1);
  const row = Math.min(Math.floor(y), rows - 2),
    column = Math.min(Math.floor(x), columns - 2);
  const a = grid.heights[row][column],
    b = grid.heights[row][column + 1];
  const c = grid.heights[row + 1][column],
    d = grid.heights[row + 1][column + 1];
  if (a === null || b === null || c === null || d === null) return null;
  const dx = x - column,
    dy = y - row;
  return (
    a * (1 - dx) * (1 - dy) +
    b * dx * (1 - dy) +
    c * (1 - dx) * dy +
    d * dx * dy
  );
}

export function terrainTile(
  grid: TerrainGrid,
  bounds: { west: number; east: number; south: number; north: number },
  size: number,
  offset: number,
): Float32Array {
  const heights = new Float32Array(size * size);
  for (let row = 0; row < size; row++) {
    // Cesium heightmaps run north→south; saved grids run south→north.
    const latitude =
      bounds.north + ((bounds.south - bounds.north) * row) / (size - 1);
    for (let column = 0; column < size; column++) {
      const longitude =
        bounds.west + ((bounds.east - bounds.west) * column) / (size - 1);
      const height = terrainHeight(grid, latitude, longitude);
      // Outside the outlined dataset only the reference ellipsoid is displayed.
      heights[row * size + column] = height === null ? 0 : height + offset;
    }
  }
  return heights;
}
