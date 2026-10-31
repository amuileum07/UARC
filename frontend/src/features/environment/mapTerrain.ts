import * as Cesium from "cesium";
import { terrainTile } from "../../lib/terrain.ts";
import type { TerrainGrid } from "../../lib/types";

export function heightmapProvider(
  options: ConstructorParameters<
    typeof Cesium.CustomHeightmapTerrainProvider
  >[0],
) {
  const provider = new Cesium.CustomHeightmapTerrainProvider(options);
  const levelZeroError = provider.getLevelMaximumGeometricError(0);
  // Cap display detail at level 18 (~2.4 m samples), finer than 5 m acquisitions.
  // Raise this cap if finer display grids are supported.
  // A leaf mask alone still lets Cesium refine upsampled tiles.
  provider.getLevelMaximumGeometricError = (level) =>
    level >= 18 ? 0 : levelZeroError / 2 ** level;
  provider.requestTileGeometry = (x, y, level) => {
    const heights = options.callback(x, y, level);
    if (heights === undefined) return undefined;
    return Promise.resolve(heights).then(
      (buffer) =>
        new Cesium.HeightmapTerrainData({
          buffer: Array.isArray(buffer) ? new Float64Array(buffer) : buffer,
          width: options.width,
          height: options.height,
          childTileMask: level < 18 ? 15 : 0,
        }),
    );
  };
  return provider;
}

export function terrainBounds(grid: TerrainGrid, offset: number) {
  let minimum = Infinity,
    maximum = -Infinity;
  for (const row of grid.heights)
    for (const height of row)
      if (height !== null) {
        minimum = Math.min(minimum, height);
        maximum = Math.max(maximum, height);
      }
  if (!Number.isFinite(minimum)) return null;
  const points = [];
  for (const height of [minimum, maximum])
    for (const latitude of [grid.south, grid.north])
      for (const longitude of [grid.west, grid.east])
        points.push(
          Cesium.Cartesian3.fromDegrees(
            longitude,
            latitude,
            height + offset + 1,
          ),
        );
  return { minimum, maximum, points };
}

export function terrainWire(grid: TerrainGrid, offset: number) {
  if (grid.heights.some((row) => row.some((height) => height === null)))
    return [];
  const rows = grid.heights.length,
    columns = grid.heights[0].length;
  const rowStep = Math.ceil((rows - 1) / 16),
    columnStep = Math.ceil((columns - 1) / 16);
  const point = (y: number, x: number) =>
    Cesium.Cartesian3.fromDegrees(
      grid.west + ((grid.east - grid.west) * x) / (columns - 1),
      grid.south + ((grid.north - grid.south) * y) / (rows - 1),
      (grid.heights[y][x] ?? 0) + offset + 1,
    );
  const lines: Cesium.Cartesian3[][] = [];
  const rowLines = new Map<number, Cesium.Cartesian3[]>();
  for (let y = 0; y < rows; y++)
    if (y % rowStep === 0 || y === rows - 1) {
      const line = Array.from({ length: columns }, (_, x) => point(y, x));
      rowLines.set(y, line);
      lines.push(line);
    }
  for (let x = 0; x < columns; x++)
    if (x % columnStep === 0 || x === columns - 1)
      lines.push(
        Array.from(
          { length: rows },
          (_, y) => rowLines.get(y)?.[x] ?? point(y, x),
        ),
      );
  return lines;
}

export function terrainMaterial(): Cesium.Material {
  // Heightmap tiles have no vertex normals; shade their actual mesh derivatives.
  return new Cesium.Material({
    fabric: {
      type: "UarcTerrainRelief",
      source: `czm_material czm_getMaterial(czm_materialInput materialInput) {
        czm_material material = czm_getDefaultMaterial(materialInput);
        vec3 surface = cross(dFdx(materialInput.positionToEyeEC), dFdy(materialInput.positionToEyeEC));
        surface /= max(length(surface), 1.0e-12);
        vec3 world = (czm_inverseView * vec4(-materialInput.positionToEyeEC, 1.0)).xyz;
        vec3 up = normalize(czm_viewRotation * (world * czm_ellipsoidInverseRadii * czm_ellipsoidInverseRadii));
        vec3 east = normalize(czm_viewRotation * vec3(-world.y, world.x, 0.0));
        vec3 north = cross(up, east);
        if (dot(surface, up) < 0.0) surface = -surface;
        vec3 light = normalize(-east + north + up);
        material.diffuse = vec3(0.3 + 0.7 * max(dot(surface, light), 0.0));
        material.alpha = 0.65;
        return material;
      }`,
    },
  });
}

export function terrainProvider(
  grid: TerrainGrid,
  offset: number,
): Cesium.CustomHeightmapTerrainProvider {
  if (grid.heights.some((row) => row.some((height) => height === null)))
    throw new Error(
      "결측 고도가 있어 3D 지형을 만들 수 없습니다. 위치·조회 반경을 바꿔 다시 가져오세요.",
    );
  const tilingScheme = new Cesium.GeographicTilingScheme();
  return heightmapProvider({
    tilingScheme,
    width: 33,
    height: 33,
    credit:
      grid.provider === "aws"
        ? new Cesium.Credit(
            'Terrain Tiles · USGS and contributors · <a href="https://github.com/tilezen/joerd/blob/master/docs/attribution.md">출처·이용 조건</a>',
            true,
          )
        : grid.provider === "opentopography"
          ? new Cesium.Credit(
              '<a href="https://opentopography.org/">OpenTopography</a>',
              true,
            )
          : "UARC imported elevation grid",
    callback: (x, y, level) => {
      const tile = tilingScheme.tileXYToRectangle(x, y, level);
      return terrainTile(
        grid,
        {
          west: Cesium.Math.toDegrees(tile.west),
          east: Cesium.Math.toDegrees(tile.east),
          south: Cesium.Math.toDegrees(tile.south),
          north: Cesium.Math.toDegrees(tile.north),
        },
        33,
        offset,
      );
    },
  });
}

export function frameMap(
  viewer: Cesium.Viewer,
  mode: "2D" | "3D",
  points: Cesium.Cartesian3[],
  minimumRadius = 750,
) {
  const sphere = Cesium.BoundingSphere.fromPoints(points);
  sphere.radius = Math.max(sphere.radius, minimumRadius);
  const canvas = viewer.scene.canvas;
  const pitch = mode === "3D" ? Cesium.Math.toRadians(-65) : -Math.PI / 2;
  const height = Cesium.Cartographic.fromCartesian(sphere.center)?.height ?? 0;
  // Before bathymetry loads, camera collision uses the zero-height ellipsoid.
  // Start above it so loading cannot push the camera away from its framed view.
  const range = Math.max(
    sphere.radius *
      2.8 *
      Math.max(1, canvas.clientHeight / Math.max(1, canvas.clientWidth)),
    (sphere.radius - height) / -Math.sin(pitch),
  );
  viewer.camera.viewBoundingSphere(
    sphere,
    new Cesium.HeadingPitchRange(0, pitch, range),
  );
  // Restore free camera navigation after framing in the local ENU frame.
  viewer.camera.lookAtTransform(Cesium.Matrix4.IDENTITY);
  viewer.scene.requestRender();
}
