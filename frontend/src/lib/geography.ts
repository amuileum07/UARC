import type { EnvironmentConfig, TelemetryResult } from "./types";

function lowerBoundTime(times: number[], time: number, end = times.length) {
  let start = 0;
  while (start < end) {
    const middle = Math.floor((start + end) / 2);
    if (times[middle] < time) start = middle + 1;
    else end = middle;
  }
  return start;
}

/** Sorted finite times from flightPath; ties and duplicates select the first row. */
export function nearestTimeIndex(times: number[], time: number): number {
  if (!times.length || !Number.isFinite(time)) return -1;
  const next = lowerBoundTime(times, time);
  if (next === 0) return 0;
  if (next === times.length || time - times[next - 1] <= times[next] - time)
    return lowerBoundTime(times, times[next - 1], next);
  return next;
}

/** Matches app.terrain.coordinates: local flat-earth flight, spherical map placement. */
export function flightCoordinates(
  latitude: number,
  longitude: number,
  east: number,
  north: number,
): [number, number] {
  const distance = Math.hypot(east, north);
  if (!Number.isFinite(distance) || distance > 10_000)
    throw new Error("지도 좌표 변환 범위는 발사점에서 10 km입니다.");
  const a = distance / 6371008.8,
    bearing = Math.atan2(east, north),
    lat = (latitude * Math.PI) / 180;
  const endLat = Math.asin(
    Math.sin(lat) * Math.cos(a) +
      Math.cos(lat) * Math.sin(a) * Math.cos(bearing),
  );
  const endLon =
    (longitude * Math.PI) / 180 +
    Math.atan2(
      Math.sin(bearing) * Math.sin(a) * Math.cos(lat),
      Math.cos(a) - Math.sin(lat) * Math.sin(endLat),
    );
  return [
    (endLat * 180) / Math.PI,
    (((endLon * 180) / Math.PI + 540) % 360) - 180,
  ];
}
/** Use the run's frozen site and absolute heights; never drape a flight on terrain. */
export function flightPath(
  telemetry: TelemetryResult,
  environment: Pick<
    EnvironmentConfig,
    "latitude" | "longitude" | "elevation_reference" | "geoid_undulation_m"
  >,
) {
  const columns = ["time_s", "x_m", "y_m", "z_asl_m"].map((name) => {
    const index = telemetry.columns.indexOf(name);
    if (index < 0) throw new Error(`궤적 자료에 ${name} 열이 없습니다.`);
    return index;
  });
  const offset =
    environment.elevation_reference === "ellipsoid"
      ? 0
      : (environment.geoid_undulation_m ?? 0);
  let previous = -Infinity;
  return telemetry.data.map((row) => {
    const [time, east, north, altitude] = columns.map((index) => row[index]);
    if (
      ![time, east, north, altitude].every(Number.isFinite) ||
      time < previous
    )
      throw new Error("궤적의 시간·위치·고도 자료가 올바르지 않습니다.");
    previous = time;
    const [latitude, longitude] = flightCoordinates(
      environment.latitude,
      environment.longitude,
      east,
      north,
    );
    return { time, latitude, longitude, height: altitude + offset };
  });
}
