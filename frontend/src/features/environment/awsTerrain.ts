import * as Cesium from "cesium";
import { terrainHeight } from "../../lib/terrain.ts";
import type { TerrainGrid } from "../../lib/types";
import { heightmapProvider } from "./mapTerrain.ts";

interface TerrainTile {
  pixels: Float32Array;
  level: number;
}
const tiles = new Map<string, Promise<TerrainTile>>();
let imageContext: CanvasRenderingContext2D | null = null;

export function decodeTerrarium(rgba: Uint8ClampedArray): Float32Array {
  if (rgba.length !== 256 * 256 * 4)
    throw new RangeError("AWS 지형 타일 크기가 올바르지 않습니다.");
  const heights = new Float32Array(256 * 256);
  for (let i = 0; i < heights.length; i++) {
    if (rgba[i * 4 + 3] !== 255)
      throw new RangeError("AWS 지형 타일에 결측 값이 있습니다.");
    heights[i] =
      rgba[i * 4] * 256 + rgba[i * 4 + 1] + rgba[i * 4 + 2] / 256 - 32768;
    if (heights[i] < -12000 || heights[i] > 10000)
      throw new RangeError("AWS 지형 타일에 유효하지 않은 고도가 있습니다.");
  }
  return heights;
}

async function loadTile(
  x: number,
  y: number,
  level: number,
): Promise<TerrainTile> {
  const key = `${level}/${x}/${y}`;
  const cached = tiles.get(key);
  if (cached) return cached;
  const promise = (async () => {
    const response = await fetch(
      `https://elevation-tiles-prod.s3.amazonaws.com/terrarium/${key}.png`,
      { signal: AbortSignal.timeout(15000) },
    );
    if (!response.ok) throw new Error("AWS 지형 타일 요청에 실패했습니다.");
    const blob = await response.blob();
    if (blob.size > 1024 * 1024)
      throw new Error("AWS 지형 타일 크기 제한을 초과했습니다.");
    const bitmap = await createImageBitmap(blob, {
      colorSpaceConversion: "none",
    });
    try {
      if (bitmap.width !== 256 || bitmap.height !== 256)
        throw new RangeError("AWS 지형 타일을 읽을 수 없습니다.");
      if (!imageContext) {
        const canvas = document.createElement("canvas");
        canvas.width = canvas.height = 256;
        imageContext = canvas.getContext("2d", { willReadFrequently: true });
      }
      const context = imageContext;
      if (!context) throw new Error("고도 이미지 읽기를 시작할 수 없습니다.");
      // Drawing and reading are synchronous; concurrent downloads share one context.
      // Clear transparent pixels so a missing cell cannot retain the previous tile.
      context.clearRect(0, 0, 256, 256);
      context.drawImage(bitmap, 0, 0);
      return {
        pixels: decodeTerrarium(context.getImageData(0, 0, 256, 256).data),
        level,
      };
    } catch (reason) {
      // Reject corrupt heights; sample valid parent data at its actual resolution.
      if (reason instanceof RangeError && level > 0)
        return loadTile(Math.floor(x / 2), Math.floor(y / 2), level - 1);
      throw reason;
    } finally {
      bitmap.close();
    }
  })();
  tiles.set(key, promise);
  if (tiles.size > 64) tiles.delete(tiles.keys().next().value ?? "");
  try {
    return await promise;
  } catch (reason) {
    if (tiles.get(key) === promise) tiles.delete(key);
    throw reason;
  }
}

export function awsHeightmap(
  x: number,
  y: number,
  level: number,
  pixels: Float32Array | null,
  grid: TerrainGrid | null | undefined,
  offset: number,
  sourceLevel = Math.min(level, 14),
): Float32Array {
  const heights = new Float32Array(65 * 65);
  const scale = 2 ** Math.max(0, level - sourceLevel);
  const count = 2 ** level;
  const longitudes = new Float64Array(65);
  const lefts = new Uint16Array(65);
  const weights = new Float64Array(65);
  for (let column = 0; column < 65; column++) {
    const u = column / 64;
    longitudes[column] = ((x + u) / count) * 360 - 180;
    const px = Math.max(
      0,
      Math.min(255, (((x % scale) + u) / scale) * 256 - 0.5),
    );
    lefts[column] = Math.min(254, Math.floor(px));
    weights[column] = px - lefts[column];
  }
  for (let row = 0; row < 65; row++) {
    const v = row / 64;
    const latitude = Cesium.Math.toDegrees(
      Cesium.WebMercatorProjection.mercatorAngleToGeodeticLatitude(
        Math.PI * (1 - (2 * (y + v)) / count),
      ),
    );
    const py = Math.max(
      0,
      Math.min(255, (((y % scale) + v) / scale) * 256 - 0.5),
    );
    const top = Math.min(254, Math.floor(py)),
      dy = py - top;
    for (let column = 0; column < 65; column++) {
      const saved = grid
        ? terrainHeight(grid, latitude, longitudes[column])
        : null;
      let height = saved ?? 0;
      if (saved === null && pixels) {
        // Edge pixels are clamped; Cesium skirts cover subpixel tile-edge differences.
        // Flight contact always uses the frozen GeoTIFF grid, never these display tiles.
        const left = lefts[column],
          dx = weights[column];
        height =
          pixels[top * 256 + left] * (1 - dx) * (1 - dy) +
          pixels[top * 256 + left + 1] * dx * (1 - dy) +
          pixels[(top + 1) * 256 + left] * (1 - dx) * dy +
          pixels[(top + 1) * 256 + left + 1] * dx * dy;
      }
      heights[row * 65 + column] =
        height + (saved === null && !pixels ? 0 : offset);
    }
  }
  return heights;
}

export function awsTerrainProvider(
  grid: TerrainGrid | null | undefined,
  offset: number,
  onError: (reason: unknown) => void,
  onFallback?: () => void,
): Cesium.CustomHeightmapTerrainProvider {
  if (grid?.heights.some((row) => row.some((height) => height === null)))
    throw new Error(
      "결측 고도가 있어 저장된 3D 계산 지형을 표시할 수 없습니다.",
    );
  const tilingScheme = new Cesium.WebMercatorTilingScheme();
  return heightmapProvider({
    tilingScheme,
    width: 65,
    height: 65,
    credit: new Cesium.Credit(
      'Terrain Tiles · USGS and contributors · <a href="https://github.com/tilezen/joerd/blob/master/docs/attribution.md">출처·이용 조건</a>',
      true,
    ),
    callback: async (x, y, level) => {
      const bounds = tilingScheme.tileXYToRectangle(x, y, level);
      if (
        grid &&
        Cesium.Math.toDegrees(bounds.west) >= grid.west &&
        Cesium.Math.toDegrees(bounds.east) <= grid.east &&
        Cesium.Math.toDegrees(bounds.south) >= grid.south &&
        Cesium.Math.toDegrees(bounds.north) <= grid.north
      )
        return awsHeightmap(x, y, level, null, grid, offset);
      const scale = 2 ** Math.max(0, level - 14);
      let tile: TerrainTile | null = null;
      try {
        tile = await loadTile(
          Math.floor(x / scale),
          Math.floor(y / scale),
          Math.min(level, 14),
        );
        if (tile.level < Math.min(level, 14)) onFallback?.();
      } catch (reason) {
        onError(reason);
      }
      return awsHeightmap(
        x,
        y,
        level,
        tile?.pixels ?? null,
        grid,
        offset,
        tile?.level,
      );
    },
  });
}
