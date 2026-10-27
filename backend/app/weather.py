"""Explicit, bounded place searches and frozen upper-air forecasts; no ODE HTTP."""

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from math import asin, cos, isfinite, radians, sin, sqrt
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from rocketpy import Environment
from rocketpy.tools import geopotential_height_to_geometric_height

from app.schemas import (
    LocationResult,
    LocationSearch,
    WeatherProfile,
    WeatherRequest,
    launch_time,
)

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
SEARCH_URL = "https://geocoding-api.open-meteo.com/v1/search"
WYOMING_URL = "https://weather.uwyo.edu/wsgi/sounding"
# Common native pressure levels for GFS and IFS 0.25°. Add levels per model only
# after checking coverage; do not infer a missing upper-air profile from surface wind.
PRESSURE_LEVELS = (1000, 925, 850, 700, 600, 500, 400, 300, 250, 200, 150, 100, 50)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Data-service redirects are not permitted.")


_OPENER = build_opener(_NoRedirect())


def _read_bytes(endpoint, parameters):
    request = Request(
        endpoint + "?" + urlencode(parameters),
        headers={
            "User-Agent": "UARC/0.1 site and weather",
            "Accept": "application/json, text/html",
        },
    )
    try:
        with _OPENER.open(request, timeout=15) as response:
            if response.geturl().split("?", 1)[0] != endpoint:
                raise ValueError("Unexpected data-service redirect.")
            raw = response.read(256 * 1024 + 1)
    except HTTPError as error:
        raise ValueError(
            f"자료 요청 실패 (HTTP {error.code}). 장소·시각·예보 제공 기간을 확인하세요."
        ) from error
    except (URLError, TimeoutError, OSError) as error:
        raise ValueError(
            "자료 서버에 연결할 수 없습니다. 기존 설정은 유지됩니다."
        ) from error
    if len(raw) > 256 * 1024:
        raise ValueError("Data-service response exceeds 256 KiB.")
    return raw, hashlib.sha256(raw).hexdigest()


def _read_json(endpoint, parameters):
    raw, digest = _read_bytes(endpoint, parameters)
    data = json.loads(raw)
    if not isinstance(data, dict) or data.get("error"):
        raise ValueError("Data service returned an invalid response.")
    return data, digest


def search_locations(request: LocationSearch) -> list[LocationResult]:
    data, _ = _read_json(
        SEARCH_URL,
        {"name": request.query, "count": 8, "language": "ko", "format": "json"},
    )
    results = data.get("results", [])
    if not isinstance(results, list) or len(results) > 8:
        raise ValueError("Invalid place-search results.")
    return [
        LocationResult(
            id=item["id"],
            name=item["name"],
            latitude=item["latitude"],
            longitude=item["longitude"],
            region=", ".join(
                dict.fromkeys(
                    item[key]
                    for key in ("admin2", "admin1", "country")
                    if item.get(key)
                )
            ),
            timezone=item.get("timezone", "UTC"),
        )
        for item in results
    ]


def _number(value):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not isfinite(value)
    ):
        raise ValueError("Missing or non-finite weather measurement.")
    return float(value)


def wind_components(speed, direction):
    speed, direction = _number(speed), _number(direction)
    if speed < 0 or not 0 <= direction <= 360:
        raise ValueError("Invalid wind speed/direction.")
    angle = radians(direction)
    return -speed * sin(angle), -speed * cos(angle)


def fetch_weather(request: WeatherRequest) -> WeatherProfile:
    if request.model == "wyoming_sounding":
        return _fetch_wyoming(request)
    if request.model == "file":
        raise ValueError("파일 기상은 파일 가져오기를 사용하세요.")
    target = launch_time(request.date, request.timezone)
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    if not today - timedelta(days=5) <= target < today + timedelta(days=10):
        raise ValueError(
            "예보 조회는 최근 5일~향후 9일 범위입니다. 실제 제공 기간은 모델에 따라 다릅니다."
        )
    start = target.replace(minute=0, second=0, microsecond=0)
    end = start if target == start else start + timedelta(hours=1)
    variables = {
        "temperature_2m": "°C",
        "surface_pressure": "hPa",
        "wind_speed_10m": "m/s",
        "wind_direction_10m": "°",
    }
    for level in PRESSURE_LEVELS:
        for key, unit in (
            ("temperature", "°C"),
            ("wind_speed", "m/s"),
            ("wind_direction", "°"),
            ("geopotential_height", "m"),
        ):
            variables[f"{key}_{level}hPa"] = unit
    offset = (
        request.geoid_undulation_m if request.elevation_reference == "ellipsoid" else 0
    )
    ground_elevation = request.elevation - request.pad_height_m
    data, digest = _read_json(
        FORECAST_URL,
        {
            "latitude": request.latitude,
            "longitude": request.longitude,
            "elevation": ground_elevation - offset,
            "models": request.model,
            "hourly": ",".join(variables),
            "wind_speed_unit": "ms",
            "temperature_unit": "celsius",
            "timezone": "GMT",
            "start_hour": start.strftime("%Y-%m-%dT%H:%M"),
            "end_hour": end.strftime("%Y-%m-%dT%H:%M"),
        },
    )
    hourly, units = data.get("hourly", {}), data.get("hourly_units", {})
    if not isinstance(hourly, dict) or not isinstance(units, dict):
        raise ValueError("Weather response must contain hourly data and units.")
    expected_times = [start.strftime("%Y-%m-%dT%H:%M")]
    if end != start:
        expected_times.append(end.strftime("%Y-%m-%dT%H:%M"))
    if data.get("utc_offset_seconds") != 0 or hourly.get("time") != expected_times:
        raise ValueError("The weather response does not cover the requested UTC time.")
    for key, unit in variables.items():
        if (
            units.get(key) != unit
            or not isinstance(hourly.get(key), list)
            or len(hourly[key]) != len(expected_times)
        ):
            raise ValueError(f"Unexpected weather units or time series: {key}.")
    fraction = (target - start).total_seconds() / 3600

    def interpolate(values):
        first = _number(values[0])
        return (
            first if end == start else first + fraction * (_number(values[1]) - first)
        )

    def wind(speed_key, direction_key):
        vectors = []
        for speed, direction in zip(
            hourly[speed_key], hourly[direction_key], strict=True
        ):
            # Meteorological direction is FROM; interpolate vectors across north.
            vectors.append(wind_components(speed, direction))
        return tuple(interpolate([v[i] for v in vectors]) for i in (0, 1))

    u, v = wind("wind_speed_10m", "wind_direction_10m")
    # Surface pressure is downscaled to the pad's ground elevation. The 2 m temperature
    # and 10 m wind anchor that point; use a boundary-layer model if finer
    # near-pad height differences are required.
    levels = [
        dict(
            altitude_m=ground_elevation,
            pressure_pa=interpolate(hourly["surface_pressure"]) * 100,
            temperature_k=interpolate(hourly["temperature_2m"]) + 273.15,
            wind_u_m_s=u,
            wind_v_m_s=v,
        )
    ]
    radius = float(Environment.calculate_earth_radius(request.latitude))
    for pressure in PRESSURE_LEVELS:
        keys = [
            f"{key}_{pressure}hPa"
            for key in (
                "temperature",
                "wind_speed",
                "wind_direction",
                "geopotential_height",
            )
        ]
        if any(value is None for key in keys for value in hourly[key]):
            raise ValueError(
                "고도별 기상 자료가 누락되었습니다. 다른 모델·시각으로 요청하세요."
            )
        height = (
            float(
                geopotential_height_to_geometric_height(
                    interpolate(hourly[f"geopotential_height_{pressure}hPa"]), radius
                )
            )
            + offset
        )
        if (
            height <= ground_elevation + 10
            or pressure * 100 >= levels[-1]["pressure_pa"]
        ):
            continue
        u, v = wind(f"wind_speed_{pressure}hPa", f"wind_direction_{pressure}hPa")
        levels.append(
            dict(
                altitude_m=height,
                pressure_pa=pressure * 100,
                temperature_k=interpolate(hourly[f"temperature_{pressure}hPa"])
                + 273.15,
                wind_u_m_s=u,
                wind_v_m_s=v,
            )
        )
    return WeatherProfile(
        request=request,
        retrieved_at=datetime.now(UTC),
        grid_latitude=data["latitude"],
        grid_longitude=data["longitude"],
        response_sha256=digest,
        levels=levels,
    )


class _SoundingPage(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks = []
        self.text = []
        self._pre = None

    def handle_starttag(self, tag, attrs):
        if tag == "pre":
            self._pre = []

    def handle_endtag(self, tag):
        if tag == "pre" and self._pre is not None:
            self.blocks.append("".join(self._pre))
            self._pre = None

    def handle_data(self, data):
        self.text.append(data)
        if self._pre is not None:
            self._pre.append(data)


def _fetch_wyoming(request: WeatherRequest) -> WeatherProfile:
    observed = launch_time(request.observation_time, "UTC")
    raw, digest = _read_bytes(
        WYOMING_URL,
        {
            "datetime": observed.strftime("%Y-%m-%d %H:%M:%S"),
            "id": request.station_id,
            "type": "TEXT:LIST",
            "src": "UNKNOWN",
        },
    )
    page = _SoundingPage()
    page.feed(raw.decode("utf-8"))
    text = " ".join(page.text)
    header = re.search(
        r"Observations for Station (\d{5}) at (\d{2}) UTC (\d{2}) ([A-Za-z]{3}) (\d{4})",
        text,
    )
    location = re.search(r"Latitude:\s*([-+\d.]+)\s+Longitude:\s*([-+\d.]+)", text)
    if header is None or location is None:
        raise ValueError("관측 자료가 없거나 Wyoming 응답 형식이 변경되었습니다.")
    station, hour, day, month, year = header.groups()
    months = {
        name: i
        for i, name in enumerate(
            (
                "Jan",
                "Feb",
                "Mar",
                "Apr",
                "May",
                "Jun",
                "Jul",
                "Aug",
                "Sep",
                "Oct",
                "Nov",
                "Dec",
            ),
            1,
        )
    }
    actual_time = datetime(int(year), months[month], int(day), int(hour), tzinfo=UTC)
    if station != request.station_id or actual_time != observed:
        raise ValueError("응답의 관측소·관측 시각이 요청과 다릅니다.")
    latitude, longitude = map(float, location.groups())
    block = next(
        (block for block in page.blocks if "PRES" in block and "HGHT" in block), None
    )
    if block is None:
        raise ValueError("Wyoming 고층 관측 표를 찾을 수 없습니다.")
    headers = next(
        line.split() for line in block.splitlines() if "PRES" in line and "HGHT" in line
    )
    expected = ["PRES", "HGHT", "TEMP", "DWPT", "RELH", "MIXR", "DRCT"]
    if (
        len(headers) < 8
        or headers[:7] != expected
        or headers[7] not in {"SPED", "SKNT"}
    ):
        raise ValueError("지원하지 않는 Wyoming 관측 열·단위입니다.")
    units = next(
        (
            line.split()
            for line in block.splitlines()
            if line.lstrip().startswith("hPa")
        ),
        [],
    )
    if units[:7] != ["hPa", "m", "C", "C", "%", "g/kg", "deg"] or (
        len(units) < 8
        or units[7] not in ({"m/s"} if headers[7] == "SPED" else {"knot", "knots"})
    ):
        raise ValueError("지원하지 않는 Wyoming 관측 단위입니다.")
    wind_factor = 1852 / 3600 if headers[7] == "SKNT" else 1
    radius = float(Environment.calculate_earth_radius(latitude))
    offset = (
        request.geoid_undulation_m if request.elevation_reference == "ellipsoid" else 0
    )
    levels, skipped = [], 0
    for line in block.splitlines():
        if not re.match(r"^\s*\d+(?:\.\d+)?\s", line):
            continue
        values = [line[i : i + 7].strip() for i in range(0, 77, 7)]
        if any(not values[i] for i in (0, 1, 2, 6, 7)):
            skipped += 1
            continue
        pressure, height, temperature, direction, speed = (
            float(values[i]) for i in (0, 1, 2, 6, 7)
        )
        if any(
            value in {-9999, 99999}
            for value in (pressure, height, temperature, direction, speed)
        ):
            skipped += 1
            continue
        u, v = wind_components(speed * wind_factor, direction)
        level = dict(
            altitude_m=float(geopotential_height_to_geometric_height(height, radius))
            + offset,
            pressure_pa=pressure * 100,
            temperature_k=temperature + 273.15,
            wind_u_m_s=u,
            wind_v_m_s=v,
        )
        if levels and level == levels[-1]:
            skipped += 1
            continue
        levels.append(level)
    levels.sort(key=lambda level: level["altitude_m"])
    a, b = radians(request.latitude), radians(latitude)
    distance = (
        6371
        * 2
        * asin(
            min(
                1,
                sqrt(
                    sin((a - b) / 2) ** 2
                    + cos(a)
                    * cos(b)
                    * sin(radians(request.longitude - longitude) / 2) ** 2
                ),
            )
        )
    )
    age = (
        launch_time(request.date, request.timezone) - observed
    ).total_seconds() / 3600
    notes = [
        f"관측 {observed.isoformat()} · 발사 시각과 {abs(age):.1f}시간 차이.",
        f"관측소와 발사장 직선거리 약 {distance:.1f} km. 관측 자료이며 해당 발사장의 예보가 아닙니다.",
    ]
    if skipped:
        notes.append(f"필수 값이 없거나 완전히 중복된 관측 {skipped}행을 제외했습니다.")
    return WeatherProfile(
        request=request,
        source="Wyoming",
        source_name=f"Station {station}",
        retrieved_at=datetime.now(UTC),
        grid_latitude=latitude,
        grid_longitude=longitude,
        response_sha256=digest,
        levels=levels,
        notes=notes,
    )
