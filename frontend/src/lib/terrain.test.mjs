import assert from "node:assert/strict";
import { test } from "node:test";
import * as Cesium from "cesium";
import {
  terrainHeight,
  terrainTile,
  defaultTerrainRequest,
  terrainMatchesSite,
  alignLaunchElevation,
  launchElevationIssue,
} from "./terrain.ts";
import { editDesign } from "./edit.ts";
import { automaticWeatherRequest, weatherRequest } from "./weather.ts";
import {
  terrainProvider,
  frameMap,
  terrainBounds,
  terrainWire,
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

test("terrain wire keeps identical lines while allocating only their shared nodes", (t) => {
  const full = {
    ...grid,
    heights: Array.from({ length: 135 }, (_, y) =>
      Array.from({ length: 135 }, (_, x) => y * 2 + x),
    ),
  };
  const fromDegrees = Cesium.Cartesian3.fromDegrees;
  const conversions = t.mock.method(Cesium.Cartesian3, "fromDegrees");
  const lines = terrainWire(full, 5);
  assert.equal(conversions.mock.callCount(), 4064);
  assert.equal(new Set(lines.flat()).size, 4064);
  const reference = full.heights.map((row, y) =>
    row.map((height, x) =>
      fromDegrees(
        full.west + ((full.east - full.west) * x) / 134,
        full.south + ((full.north - full.south) * y) / 134,
        height + 6,
      ),
    ),
  );
  const indices = Array.from({ length: 135 }, (_, i) => i).filter(
    (i) => i % Math.ceil(134 / 16) === 0 || i === 134,
  );
  assert.deepEqual(lines, [
    ...indices.map((y) => reference[y]),
    ...indices.map((x) => reference.map((row) => row[x])),
  ]);
});

test("terrain camera bounds include interior height extrema without wire generation", () => {
  const full = {
    ...grid,
    heights: [
      [-20, 1, 2],
      [3, 900, 4],
      [5, 6, 7],
    ],
  };
  const bounds = terrainBounds(full, 5);
  assert.equal(bounds.minimum, -20);
  assert.equal(bounds.maximum, 900);
  assert.equal(bounds.points.length, 8);
  const sphere = Cesium.BoundingSphere.fromPoints(bounds.points);
  for (let y = 0; y < 3; y++)
    for (let x = 0; x < 3; x++)
      assert.ok(
        Cesium.Cartesian3.distance(
          sphere.center,
          Cesium.Cartesian3.fromDegrees(
            full.west + ((full.east - full.west) * x) / 2,
            full.south + ((full.north - full.south) * y) / 2,
            full.heights[y][x] + 6,
          ),
        ) <=
          sphere.radius + 0.0001,
      );
  assert.equal(
    terrainBounds(
      {
        ...grid,
        heights: [
          [null, null],
          [null, null],
        ],
      },
      0,
    ),
    null,
  );
});

test("terrain providers stop adding geometric detail beyond supported source resolution", async () => {
  const location = Cesium.Cartographic.fromDegrees(20.01, 10.01);
  for (const provider of [
    terrainProvider(grid, 0),
    awsTerrainProvider(grid, 0, assert.fail),
  ]) {
    assert.ok(provider.getLevelMaximumGeometricError(17) > 0);
    for (const level of [18, 19, 30, 31])
      assert.equal(provider.getLevelMaximumGeometricError(level), 0);
    for (const level of [17, 18, 19]) {
      const { x, y } = provider.tilingScheme.positionToTileXY(location, level);
      const data = await provider.requestTileGeometry(x, y, level);
      for (const dx of [0, 1])
        for (const dy of [0, 1])
          assert.equal(
            data.isChildAvailable(x, y, x * 2 + dx, y * 2 + dy),
            level < 18,
          );
    }
  }
});

test("terrain-following updates height/reference atomically and preserves manual elevations", () => {
  const env = {
    latitude: 10.01,
    longitude: 20.01,
    datum: "WGS84",
    elevation: 999,
    elevation_mode: "terrain",
    elevation_reference: "unknown",
    geoid_undulation_m: 30,
    pad_height_m: 2,
    terrain: { ...grid, reference: "EGM96" },
    wind_u: 7,
    pressure: [
      [0, 101000],
      [1000, 90000],
    ],
  };
  const aligned = editDesign({ environment: env }, ["environment"], env);
  assert.ok(Math.abs(aligned.environment.elevation - 27) < 1e-9);
  assert.equal(aligned.environment.elevation_reference, "EGM96");
  assert.equal(aligned.environment.geoid_undulation_m, null);
  assert.equal(aligned.environment.pressure, env.pressure);
  assert.equal(aligned.environment.wind_u, 7);
  assert.equal(env.elevation, 999);
  assert.equal(launchElevationIssue(aligned.environment), "");
  assert.equal(alignLaunchElevation(aligned.environment), aligned.environment);
  const taller = editDesign(aligned, ["environment", "pad_height_m"], 12);
  assert.ok(Math.abs(taller.environment.elevation - 37) < 1e-9);
  const manual = editDesign(
    taller,
    ["environment", "elevation_mode"],
    "manual",
  );
  const measured = editDesign(manual, ["environment", "elevation"], 432.1);
  const changed = editDesign(measured, ["environment", "pad_height_m"], 0);
  assert.equal(changed.environment.elevation, 432.1);
  assert.equal(
    launchElevationIssue({ ...changed.environment, terrain: null }),
    "",
  );
  const legacy = { ...env };
  delete legacy.elevation_mode;
  assert.equal(
    editDesign({ environment: legacy }, ["environment", "pad_height_m"], 3)
      .environment.elevation,
    999,
  );
});

test("automatic heights wait for usable terrain before requesting weather", () => {
  const env = {
    latitude: 10.01,
    longitude: 20.01,
    datum: "WGS84",
    elevation: 27,
    elevation_mode: "terrain",
    elevation_reference: "EGM96",
    pad_height_m: 2,
    terrain: { ...grid, reference: "EGM96" },
    date: "2026-10-27T12:00",
    timezone: "UTC",
  };
  for (const changes of [
    { terrain: null },
    { datum: "NAD83" },
    { latitude: NaN },
    { longitude: 25 },
    { pad_height_m: -1 },
    { pad_height_m: Infinity },
    { terrain: { ...grid, reference: "unknown" } },
    {
      terrain: {
        ...grid,
        reference: "EGM96",
        heights: [
          [10, null],
          [30, 40],
        ],
      },
    },
  ]) {
    const invalid = { ...env, ...changes };
    assert.equal(alignLaunchElevation(invalid), null);
    assert.ok(launchElevationIssue(invalid));
    assert.throws(() => weatherRequest(invalid, "gfs_seamless"));
    assert.equal(
      automaticWeatherRequest({
        ...invalid,
        weather_profile: { request: { model: "gfs_seamless" } },
      }),
      null,
    );
  }
  const negative = alignLaunchElevation({
    ...env,
    terrain: {
      ...grid,
      reference: "EGM96",
      heights: [
        [-40, -30],
        [-20, -10],
      ],
    },
  });
  assert.ok(Math.abs(negative.elevation + 23) < 1e-9);
  assert.equal(negative.elevation_reference, "EGM96");
});

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
  const seabed = [Cesium.Cartesian3.fromDegrees(0, 0, -4931)];
  frameMap(viewer, "3D", seabed);
  assert.ok(
    -4931 + calls[12].offset.range * -Math.sin(calls[12].offset.pitch) >=
      750 - 0.0001,
  );
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
  rgba.set([71, 132, 53, 255], 0);
  assert.throws(() => decodeTerrarium(rgba), {
    name: "RangeError",
    message: /유효하지 않은 고도/,
  });
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
  assert.ok(
    [...awsHeightmap(point.x, point.y, 14, pixels, frozen, 5, 12)].every(
      (h) => h === 12,
    ),
  );
});

function terrainImages(t, image) {
  const original = {
    document: globalThis.document,
    createImageBitmap: globalThis.createImageBitmap,
  };
  t.after(() => {
    for (const [key, value] of Object.entries(original)) {
      if (value === undefined) delete globalThis[key];
      else globalThis[key] = value;
    }
  });
  const requests = [];
  let closed = 0;
  let canvases = 0,
    clears = 0;
  t.mock.method(globalThis, "fetch", async (url) => {
    const key = url.split("/terrarium/")[1].replace(".png", "");
    requests.push(key);
    const rgba = image(key);
    return { ok: true, blob: async () => ({ size: rgba.length, rgba }) };
  });
  globalThis.createImageBitmap = async (blob) => ({
    width: 256,
    height: 256,
    rgba: blob.rgba,
    close: () => closed++,
  });
  globalThis.document = {
    createElement: () => {
      canvases++;
      const pixels = new Uint8ClampedArray(256 * 256 * 4);
      return {
        getContext: () => ({
          clearRect: () => {
            pixels.fill(0);
            clears++;
          },
          drawImage: (bitmap) => {
            for (let i = 0; i < pixels.length; i += 4)
              if (bitmap.rgba[i + 3] !== 0)
                pixels.set(bitmap.rgba.subarray(i, i + 4), i);
          },
          getImageData: () => ({ data: pixels }),
        }),
      };
    },
  };
  return {
    requests,
    closed: () => closed,
    canvases: () => canvases,
    clears: () => clears,
  };
}

test("concurrent tile decoding reuses one canvas and clears transparent source pixels", async (t) => {
  const rgba = (height) => {
    const pixels = new Uint8ClampedArray(256 * 256 * 4);
    for (let i = 0; i < pixels.length; i += 4)
      pixels.set([128, height, 0, 255], i);
    return pixels;
  };
  const images = terrainImages(t, (key) => {
    if (key === "2/2/1") return new Uint8ClampedArray(256 * 256 * 4);
    return rgba({ "2/0/1": 16, "2/1/1": 32, "1/1/0": 64 }[key]);
  });
  const { awsTerrainProvider: freshProvider } = await import(
    "../features/environment/awsTerrain.ts?shared-canvas"
  );
  let fallbacks = 0;
  const provider = freshProvider(
    null,
    0,
    (reason) => assert.fail(String(reason)),
    () => fallbacks++,
  );
  const tiles = await Promise.all([
    provider.requestTileGeometry(0, 1, 2),
    provider.requestTileGeometry(1, 1, 2),
  ]);
  const heights = tiles.map((tile, x) => {
    const bounds = provider.tilingScheme.tileXYToRectangle(x, 1, 2);
    return tile.interpolateHeight(bounds, bounds.west, bounds.north);
  });
  assert.deepEqual(heights, [16, 32]);
  await provider.requestTileGeometry(2, 1, 2);
  assert.equal(fallbacks, 1);
  assert.equal(images.canvases(), 1);
  assert.equal(images.clears(), 4);
  assert.equal(images.closed(), 4);
});

test("invalid AWS display heights use a cached valid parent with correct child sampling", async (t) => {
  const rgba = new Uint8ClampedArray(256 * 256 * 4);
  for (let y = 0; y < 256; y++)
    for (let x = 0; x < 256; x++) {
      const value = 32768 + y * 10 + x;
      rgba.set(
        [Math.floor(value / 256), value % 256, 0, 255],
        (y * 256 + x) * 4,
      );
    }
  const invalid = rgba.slice();
  invalid.set([71, 132, 53, 255], 0);
  const images = terrainImages(t, (key) => {
    assert.ok(["3/3/3", "2/1/1"].includes(key));
    return key === "3/3/3" ? invalid : rgba;
  });
  let fallbacks = 0;
  const provider = awsTerrainProvider(
    null,
    5,
    (reason) => assert.fail(String(reason)),
    () => fallbacks++,
  );
  const tile = await provider.requestTileGeometry(3, 3, 3);
  const bounds = provider.tilingScheme.tileXYToRectangle(3, 3, 3);
  assert.equal(
    tile.interpolateHeight(bounds, bounds.west, bounds.north),
    127.5 * 11 + 5,
  );
  assert.equal(
    tile.interpolateHeight(bounds, bounds.east, bounds.south),
    255 * 11 + 5,
  );
  await provider.requestTileGeometry(3, 3, 3);
  assert.deepEqual(images.requests, ["3/3/3", "2/1/1"]);
  assert.equal(images.closed(), 2);
  assert.equal(fallbacks, 2);
});

test("AWS network failures retain their cause and retry without requesting parent tiles", async (t) => {
  const reason = new TypeError("Failed to fetch");
  const images = terrainImages(t, () => {
    throw reason;
  });
  const errors = [];
  const provider = awsTerrainProvider(null, 0, (error) => errors.push(error));
  await provider.requestTileGeometry(7, 7, 4);
  await provider.requestTileGeometry(7, 7, 4);
  assert.deepEqual(images.requests, ["4/7/7", "4/7/7"]);
  assert.deepEqual(errors, [reason, reason]);
});

test("invalid AWS data stops at the root and reports a data error", async (t) => {
  const rgba = new Uint8ClampedArray(256 * 256 * 4);
  for (let i = 3; i < rgba.length; i += 4) rgba[i] = 255;
  const images = terrainImages(t, () => rgba);
  const errors = [];
  const provider = awsTerrainProvider(null, 0, (error) => errors.push(error));
  await provider.requestTileGeometry(0, 0, 1);
  assert.deepEqual(images.requests, ["1/0/0", "0/0/0"]);
  assert.equal(errors.length, 1);
  assert.ok(errors[0] instanceof RangeError);
  assert.equal(images.closed(), 2);
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
