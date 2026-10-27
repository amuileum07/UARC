import assert from "node:assert/strict";
import { test } from "node:test";
import * as Cesium from "cesium";
import {
  terrainHeight,
  terrainTile,
  defaultTerrainRequest,
  terrainMatchesSite,
} from "./terrain.ts";
import { editDesign } from "./edit.ts";
import {
  terrainProvider,
  frameMap,
} from "../features/environment/mapTerrain.ts";
import {
  decodeTerrarium,
  awsHeightmap,
  awsTerrainProvider,
} from "../features/environment/awsTerrain.ts";
const grid = {
  south: 10,
  north: 10.02,
  west: 20,
  east: 20.02,
  heights: [
    [10, 20],
    [30, 40],
  ],
};

test("display interpolation matches saved south-to-north grids and preserves data gaps", () => {
  assert.ok(Math.abs(terrainHeight(grid, 10.01, 20.01) - 25) < 1e-9);
  assert.equal(terrainHeight(grid, 10, 20), 10);
  assert.equal(terrainHeight(grid, 10.02, 20.02), 40);
  assert.equal(terrainHeight(grid, 11, 20), null);
  const missing = {
    ...grid,
    heights: [
      [10, null],
      [30, 40],
    ],
  };
  assert.equal(terrainHeight(missing, 10.01, 20.01), null);
  assert.throws(() => terrainProvider(missing, 0), /결측/);
});
test("Cesium tile rows run north-to-south, apply N once, and keep negative elevations", () => {
  const bounds = {
    south: grid.south,
    north: grid.north,
    west: grid.west,
    east: grid.east,
  };
  assert.deepEqual([...terrainTile(grid, bounds, 2, 30)], [60, 70, 40, 50]);
  assert.deepEqual(
    [
      ...terrainTile(
        {
          ...grid,
          heights: [
            [-40, -30],
            [-20, -10],
          ],
        },
        bounds,
        2,
        0,
      ),
    ],
    [-20, -10, -40, -30],
  );
  const outside = { south: 11, north: 11.02, west: 20, east: 20.02 };
  assert.deepEqual([...terrainTile(grid, outside, 2, 30)], [0, 0, 0, 0]);
});
test("actual Cesium provider exposes interpolated terrain to the globe and joins tile edges", async () => {
  const provider = terrainProvider(grid, 5);
  const location = Cesium.Cartographic.fromDegrees(20.01, 10.01);
  const index = provider.tilingScheme.positionToTileXY(location, 15);
  const rectangle = provider.tilingScheme.tileXYToRectangle(
    index.x,
    index.y,
    15,
  );
  const data = await provider.requestTileGeometry(index.x, index.y, 15);
  assert.ok(
    Math.abs(
      data.interpolateHeight(rectangle, location.longitude, location.latitude) -
        30,
    ) < 0.0001,
  );
  const neighbor = provider.tilingScheme.tileXYToRectangle(
    index.x + 1,
    index.y,
    15,
  );
  const next = await provider.requestTileGeometry(index.x + 1, index.y, 15);
  const latitude = (rectangle.south + rectangle.north) / 2;
  assert.ok(
    Math.abs(
      data.interpolateHeight(rectangle, rectangle.east, latitude) -
        next.interpolateHeight(neighbor, neighbor.west, latitude),
    ) < 0.0001,
  );
});
test("map framing faces north with a steep 3D view, correct range, and unlocked navigation", () => {
  const calls = [];
  const viewer = {
    camera: {
      viewBoundingSphere: (sphere, offset) => calls.push({ sphere, offset }),
      lookAtTransform: (matrix) => calls.push(matrix),
    },
    scene: {
      canvas: { clientWidth: 1000, clientHeight: 500 },
      requestRender: () => calls.push("render"),
    },
  };
  const points = [Cesium.Cartesian3.fromDegrees(129.3, 35.55, 700)];
  frameMap(viewer, "3D", points);
  assert.equal(calls[0].offset.heading, 0);
  assert.equal(calls[0].offset.pitch, Cesium.Math.toRadians(-65));
  assert.equal(calls[0].offset.range, 750 * 2.8);
  assert.equal(calls[0].sphere.radius, 750);
  assert.equal(calls[1], Cesium.Matrix4.IDENTITY);
  frameMap(viewer, "2D", points);
  assert.equal(calls[3].offset.pitch, -Math.PI / 2);
  assert.equal(calls[3].offset.heading, 0);
  assert.equal(calls[3].offset.range, 750 * 2.8);
  frameMap(viewer, "3D", points, 30);
  assert.equal(calls[6].sphere.radius, 30);
  assert.equal(calls[6].offset.range, 30 * 2.8);
  viewer.scene.canvas.clientWidth = 250;
  frameMap(viewer, "3D", points, 30);
  assert.equal(calls[9].offset.range, 30 * 2.8 * 2);
});

test("editing geometry or weather preserves unchanged terrain identity without mutating previous designs", () => {
  const design = {
    environment: {
      latitude: 35,
      longitude: 129,
      datum: "WGS84",
      terrain: grid,
      wind_u: 0,
    },
    components: [
      { id: "body", length: 1 },
      { id: "payload", mass: 1 },
    ],
  };
  const changed = editDesign(design, ["components", "0", "length"], 2);
  assert.equal(changed.environment, design.environment);
  assert.equal(changed.environment.terrain, grid);
  assert.equal(changed.components[1], design.components[1]);
  assert.notEqual(changed.components[0], design.components[0]);
  assert.equal(design.components[0].length, 1);
  const weather = editDesign(changed, ["environment", "wind_u"], 5);
  assert.equal(weather.environment.terrain, grid);
  assert.equal(changed.environment.wind_u, 0);
  const moved = editDesign(weather, ["environment", "latitude"], 36);
  assert.equal(moved.environment.terrain, null);
  assert.equal(weather.environment.terrain, grid);
});

test("automatic AWS requests require a valid WGS84 site and preserve frozen terrain", () => {
  const env = {
    latitude: 35.55,
    longitude: 129.3,
    datum: "WGS84",
    elevation: 100,
    terrain: null,
  };
  const area = defaultTerrainRequest(env);
  assert.equal(area.provider, "aws");
  assert.equal(area.spacing_m, 30);
  assert.equal(defaultTerrainRequest(env, 2000, 15).radius_m, 2000);
  assert.equal(defaultTerrainRequest(env, 2000, 15).spacing_m, 15);
  assert.equal(defaultTerrainRequest(env, 50, 30), null);
  assert.equal(defaultTerrainRequest(env, 1000, NaN), null);
  assert.equal(defaultTerrainRequest({ ...env, terrain: grid }), null);
  assert.equal(defaultTerrainRequest({ ...env, datum: "SIRGAS2000" }), null);
  assert.equal(defaultTerrainRequest({ ...env, latitude: Infinity }), null);
  assert.equal(defaultTerrainRequest({ ...env, latitude: 81 }), null);
  assert.equal(terrainMatchesSite({ ...env, elevation: 200 }, area), true);
  assert.equal(terrainMatchesSite({ ...env, longitude: 128 }, area), false);
});

test("Terrarium decoding keeps submeter and negative real heights and rejects missing pixels", () => {
  const rgba = new Uint8ClampedArray(256 * 256 * 4);
  for (let i = 0; i < 256 * 256; i++) {
    rgba[i * 4] = 128;
    rgba[i * 4 + 3] = 255;
  }
  rgba.set([127, 255, 128, 255], 4);
  rgba.set([137, 219, 68, 255], 8);
  const heights = decodeTerrarium(rgba);
  assert.equal(heights[0], 0);
  assert.equal(heights[1], -0.5);
  assert.equal(heights[2], 2523.265625);
  assert.throws(() => decodeTerrarium(new Uint8ClampedArray(4)), /크기/);
  rgba[3] = 0;
  assert.throws(() => decodeTerrarium(rgba), /결측/);
});

test("streamed terrain preserves saved calculation heights and samples parent tiles above the source zoom limit", () => {
  const pixels = new Float32Array(256 * 256).fill(100);
  assert.ok(
    [...awsHeightmap(1, 1, 2, pixels, null, 5)].every((h) => h === 105),
  );
  const frozen = {
    south: 9,
    north: 11,
    west: 19,
    east: 21,
    heights: [
      [7, 7],
      [7, 7],
    ],
  };
  const tiling = new Cesium.WebMercatorTilingScheme();
  const point = tiling.positionToTileXY(
    Cesium.Cartographic.fromDegrees(20, 10),
    14,
  );
  assert.ok(
    [...awsHeightmap(point.x, point.y, 14, pixels, frozen, 5)].every(
      (h) => h === 12,
    ),
  );
  assert.ok(
    [...awsHeightmap(point.x, point.y, 14, null, frozen, 5)].every(
      (h) => h === 12,
    ),
  );
  for (let y = 0; y < 256; y++)
    for (let x = 0; x < 256; x++) pixels[y * 256 + x] = y * 10 + x;
  const child = awsHeightmap(1, 1, 15, pixels, null, 0);
  assert.equal(child[0], 127.5 * 11);
  assert.equal(child.at(-1), 255 * 11);
});

test("fully saved tiles render without network and missing calculation cells are rejected", async () => {
  const frozen = {
    south: 9,
    north: 11,
    west: 19,
    east: 21,
    heights: [
      [7, 7],
      [7, 7],
    ],
  };
  const provider = awsTerrainProvider(frozen, 5, () =>
    assert.fail("unexpected network fallback"),
  );
  const point = provider.tilingScheme.positionToTileXY(
    Cesium.Cartographic.fromDegrees(20, 10),
    14,
  );
  const rectangle = provider.tilingScheme.tileXYToRectangle(
    point.x,
    point.y,
    14,
  );
  const data = await provider.requestTileGeometry(point.x, point.y, 14);
  assert.ok(
    Math.abs(
      data.interpolateHeight(
        rectangle,
        (20 * Math.PI) / 180,
        (10 * Math.PI) / 180,
      ) - 12,
    ) < 1e-4,
  );
  assert.throws(
    () =>
      awsTerrainProvider(
        {
          ...frozen,
          heights: [
            [null, 7],
            [7, 7],
          ],
        },
        0,
        () => {},
      ),
    /결측/,
  );
});
