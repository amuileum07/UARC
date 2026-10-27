import * as Cesium from "cesium";
import { terrainTile } from "../../lib/terrain.ts";
import type { TerrainGrid } from "../../lib/types";

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
  return new Cesium.CustomHeightmapTerrainProvider({
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
) {
  const sphere = Cesium.BoundingSphere.fromPoints(points);
  sphere.radius = Math.max(sphere.radius, 750);
  const canvas = viewer.scene.canvas;
  const range =
    sphere.radius *
    2.8 *
    Math.max(1, canvas.clientHeight / Math.max(1, canvas.clientWidth));
  viewer.camera.viewBoundingSphere(
    sphere,
    new Cesium.HeadingPitchRange(
      0,
      mode === "3D" ? Cesium.Math.toRadians(-65) : -Math.PI / 2,
      range,
    ),
  );
  // Restore free camera navigation after framing in the local ENU frame.
  viewer.camera.lookAtTransform(Cesium.Matrix4.IDENTITY);
  viewer.scene.requestRender();
}
