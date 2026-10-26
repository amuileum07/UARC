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
