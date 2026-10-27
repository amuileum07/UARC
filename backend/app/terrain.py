"""Bounded elevation acquisition, local coordinates, and bilinear ground heights."""

import hashlib
import json
from datetime import UTC, datetime
from math import asin, atan2, cos, degrees, hypot, radians, sin
from threading import Lock
from time import monotonic
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.schemas import EnvironmentConfig, TerrainGrid, TerrainRequest

_FETCH_LOCK = Lock()
_LAST_FETCH = 0.0
EARTH_RADIUS_M = 6371008.8


def coordinates(latitude, longitude, east_m, north_m):
    """Local flat-flight displacement mapped by distance/bearing, limited to 10 km."""
    distance = hypot(east_m, north_m)
    if distance > 10_000:
        raise ValueError("Map conversion is limited to 10 km from launch.")
    angular = distance / EARTH_RADIUS_M
    bearing = atan2(east_m, north_m)
    lat = radians(latitude)
    end_lat = asin(sin(lat) * cos(angular) + cos(lat) * sin(angular) * cos(bearing))
    end_lon = radians(longitude) + atan2(
        sin(bearing) * sin(angular) * cos(lat),
        cos(angular) - sin(lat) * sin(end_lat),
    )
    return degrees(end_lat), (degrees(end_lon) + 180) % 360 - 180


def sample_grid(grid: TerrainGrid, latitude: float, longitude: float) -> float:
    if (
        not grid.south <= latitude <= grid.north
        or not grid.west <= longitude <= grid.east
    ):
        raise ValueError("Trajectory is outside terrain coverage; enlarge the grid.")
    height, width = len(grid.heights), len(grid.heights[0])
    y = (latitude - grid.south) / (grid.north - grid.south) * (height - 1)
    x = (longitude - grid.west) / (grid.east - grid.west) * (width - 1)
    row, column = min(int(y), height - 2), min(int(x), width - 2)
    dx, dy = x - column, y - row
    cells = [grid.heights[r][c] for r in (row, row + 1) for c in (column, column + 1)]
    if any(value is None for value in cells):
        raise ValueError("Terrain has missing elevation data at this location.")
    a, b, c, d = cells
    return a * (1 - dx) * (1 - dy) + b * dx * (1 - dy) + c * (1 - dx) * dy + d * dx * dy


class GroundSurface:
    def __init__(self, config: EnvironmentConfig):
        self.config = config

    def at(self, east_m: float, north_m: float) -> float:
        config = self.config
        if config.terrain is None:
            raise ValueError("No terrain dataset is attached.")
        if config.datum != "WGS84":
            raise ValueError("Terrain checks require WGS84 coordinates.")
        lat, lon = coordinates(config.latitude, config.longitude, east_m, north_m)
        height = sample_grid(config.terrain, lat, lon)
        if "unknown" in (config.elevation_reference, config.terrain.reference):
            raise ValueError("Vertical height reference is unknown.")
        if config.elevation_reference != config.terrain.reference:
            if "ellipsoid" not in (
                config.elevation_reference,
                config.terrain.reference,
            ):
                raise ValueError(
                    "Different orthometric datums require an explicit vertical transformation."
                )
            if config.geoid_undulation_m is None:
                raise ValueError(
                    "Geoid undulation is needed to compare height references."
                )
            # h = H + N; the grid's H/h is converted to the environment's reference.
            height += config.geoid_undulation_m * (
                1 if config.elevation_reference == "ellipsoid" else -1
            )
        return height


def check_elevation(config: EnvironmentConfig) -> dict:
    try:
        ground = GroundSurface(config).at(0, 0)
    except ValueError as error:
        return {
            "status": "unverified",
            "message": str(error),
            "ground_elevation_m": None,
            "difference_m": None,
        }
    difference = config.elevation - (ground + config.pad_height_m)
    return {
        "status": "warning" if abs(difference) > config.elevation_tolerance_m else "ok",
        "message": "Launch elevation compared with terrain plus pad height.",
        "ground_elevation_m": ground,
        "difference_m": difference,
    }


def fetch_terrain(request: TerrainRequest) -> TerrainGrid:
    if request.provider != "opentopodata":
        from app.terrain_sources import fetch_dem

        return fetch_dem(request)
    return _fetch_opentopodata(request)


def _fetch_opentopodata(request: TerrainRequest) -> TerrainGrid:
    """One explicit request: 81 samples, fixed HTTPS endpoint, no arbitrary URLs."""
    global _LAST_FETCH
    with _FETCH_LOCK:
        if monotonic() - _LAST_FETCH < 1.1:
            raise ValueError("Wait at least 1.1 seconds between elevation requests.")
        _LAST_FETCH = monotonic()
        south, west = coordinates(
            request.latitude, request.longitude, -request.radius_m, -request.radius_m
        )
        north, east = coordinates(
            request.latitude, request.longitude, request.radius_m, request.radius_m
        )
        points = [
            (south + (north - south) * y / 8, west + (east - west) * x / 8)
            for y in range(9)
            for x in range(9)
        ]
        query = urlencode(
            {
                "locations": "|".join(f"{lat:.7f},{lon:.7f}" for lat, lon in points),
                "interpolation": "bilinear",
            }
        )
        url = "https://api.opentopodata.org/v1/srtm90m?" + query
        with urlopen(
            Request(url, headers={"User-Agent": "UARC/0.1 terrain preview"}), timeout=15
        ) as response:
            if (
                response.geturl().split("?", 1)[0]
                != "https://api.opentopodata.org/v1/srtm90m"
            ):
                raise ValueError("Unexpected terrain service redirect.")
            raw = response.read(128 * 1024 + 1)
        if len(raw) > 128 * 1024:
            raise ValueError("Terrain response exceeds 128 KiB.")
        data = json.loads(raw)
        results = data.get("results", [])
        if data.get("status") != "OK" or len(results) != len(points):
            raise ValueError("Elevation service returned an incomplete grid.")
        for item, (lat, lon) in zip(results, points, strict=True):
            location = item["location"]
            if abs(location["lat"] - lat) > 1e-5 or abs(location["lng"] - lon) > 1e-5:
                raise ValueError("Elevation service returned unexpected coordinates.")
        heights = [item["elevation"] for item in results]
        return TerrainGrid(
            south=south,
            north=north,
            west=west,
            east=east,
            heights=[heights[i : i + 9] for i in range(0, 81, 9)],
            reference="EGM96",
            provider="opentopodata",
            source="Open Topo Data / SRTM90m; response SHA256 "
            + hashlib.sha256(raw).hexdigest(),
            retrieved_at=datetime.now(UTC).isoformat(),
            source_resolution_m=90.0,
            sampling_distance_m=request.radius_m / 4,
        )
