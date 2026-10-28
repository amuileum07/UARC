"""Offline provider, time/height/vector conversions, persistence, and solver checks."""

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

from pydantic import ValidationError

from app.bridge import DesktopBridge
from app.design import compile_design
from app.schemas import (
    EnvironmentConfig,
    FlightConfig,
    LocationSearch,
    RocketConfig,
    RocketDesign,
    WeatherProfile,
    WeatherRequest,
    launch_time,
)
from app.simulation.engine import build_environment, build_rocket, run_simulation
from app.storage import RunStore
from app.weather import (
    FORECAST_URL,
    PLACE_URL,
    PRESSURE_LEVELS,
    SEARCH_URL,
    WYOMING_URL,
    _NoRedirect,
    _read_json,
    _search_places,
    fetch_weather,
    search_locations,
)


def weather_request(**changes):
    date = datetime.now(UTC).replace(hour=3, minute=30, second=0, microsecond=0)
    values = dict(
        latitude=35.0,
        longitude=129.0,
        elevation=100.0,
        elevation_reference="EGM96",
        date=date,
        timezone="Asia/Seoul",
        model="gfs_seamless",
    )
    return WeatherRequest(**(values | changes))


def response(request):
    target = launch_time(request.date, request.timezone)
    start = target.replace(minute=0, second=0, microsecond=0)
    times = [start]
    if target != start:
        times.append(start + timedelta(hours=1))
    count = len(times)
    hourly = {"time": [t.strftime("%Y-%m-%dT%H:%M") for t in times]}
    units = {"time": "iso8601"}
    for key, value, unit in (
        ("temperature_2m", 20, "°C"),
        ("surface_pressure", 1000, "hPa"),
        ("wind_speed_10m", 10, "m/s"),
        ("wind_direction_10m", 0, "°"),
    ):
        hourly[key] = [value] * count
        units[key] = unit
    for i, pressure in enumerate(PRESSURE_LEVELS):
        for key, value, unit in (
            ("temperature", 18 - i * 3, "°C"),
            ("wind_speed", 10, "m/s"),
            ("wind_direction", 90, "°"),
            ("geopotential_height", 200 + i * 1500, "m"),
        ):
            name = f"{key}_{pressure}hPa"
            hourly[name] = [value] * count
            units[name] = unit
    return {
        "latitude": 35.1,
        "longitude": 129.1,
        "utc_offset_seconds": 0,
        "hourly": hourly,
        "hourly_units": units,
    }


def profile(request=None):
    request = request or weather_request()
    with patch("app.weather._read_json", return_value=(response(request), "a" * 64)):
        return fetch_weather(request)


def environment(saved):
    r = saved.request
    return EnvironmentConfig(
        latitude=r.latitude,
        longitude=r.longitude,
        elevation=r.elevation,
        pad_height_m=r.pad_height_m,
        elevation_reference=r.elevation_reference,
        geoid_undulation_m=r.geoid_undulation_m,
        date=r.date,
        timezone=r.timezone,
        datum="WGS84",
        weather_profile=saved,
    )


class WeatherTests(unittest.TestCase):
    def test_wyoming_observation_units_station_time_and_notes(self):
        observed = datetime(2019, 2, 5, 12, tzinfo=UTC)
        request = weather_request(
            model="wyoming_sounding",
            station_id="83779",
            observation_time=observed,
            date=observed,
            elevation=1000,
        )
        for field, unit, factor in (("SPED", "m/s", 1), ("SKNT", "knot", 1852 / 3600)):
            rows = "\n".join(
                "".join(f"{value:>7}" for value in values)
                for values in (
                    [935, 722, 25.6, 17, 61, 13, 90, 10, 0, 0, 0],
                    [850, 1500, 20, 15, 60, 12, 0, 20, 0, 0, 0],
                    [800, 2000, 15, 10, 60, 12, "", "", 0, 0, 0],
                )
            )
            page = f"<h1>Observations for Station 83779 at 12 UTC 05 Feb 2019</h1><i>Latitude: -23.520 Longitude: -46.630</i><pre>   PRES   HGHT   TEMP   DWPT   RELH   MIXR   DRCT   {field}\n hPa m C C % g/kg deg {unit}\n{rows}</pre>".encode()
            with (
                self.subTest(field=field),
                patch("app.weather._read_bytes", return_value=(page, "d" * 64)) as read,
            ):
                saved = fetch_weather(request)
                self.assertEqual(saved.source, "Wyoming")
                self.assertEqual(len(saved.levels), 2)
                self.assertAlmostEqual(saved.levels[0].wind_u_m_s, -10 * factor)
                self.assertEqual(saved.levels[0].pressure_pa, 93500)
                self.assertGreater(saved.levels[0].altitude_m, 722)
                self.assertEqual(saved.grid_latitude, -23.52)
                self.assertTrue(any("거리" in note for note in saved.notes))
                self.assertTrue(any("1행" in note for note in saved.notes))
                self.assertEqual(read.call_args.args[0], WYOMING_URL)
                self.assertEqual(read.call_args.args[1]["id"], "83779")
        for altered in (
            page.replace(b"83779", b"83778"),
            page.replace(b"12 UTC", b"00 UTC"),
            b"<h1>No data</h1>",
            page.replace(b"knot", b"km/h"),
        ):
            with (
                patch("app.weather._read_bytes", return_value=(altered, "d" * 64)),
                self.assertRaises(ValueError),
            ):
                fetch_weather(request)

    def test_wyoming_requires_explicit_station_and_utc_observation_interval(self):
        for changes in (
            {},
            {"station_id": "47122"},
            {"station_id": "abcd", "observation_time": "2020-01-01T00:00Z"},
            {"station_id": "47122", "observation_time": "2020-01-01T01:00Z"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                weather_request(model="wyoming_sounding", **changes)

    def test_time_zone_and_dst_validation(self):
        self.assertEqual(
            launch_time((2026, 10, 26, 12), "UTC"),
            datetime(2026, 10, 26, 12, tzinfo=UTC),
        )
        self.assertEqual(
            launch_time((2026, 10, 26, 12), "Asia/Seoul"),
            datetime(2026, 10, 26, 3, tzinfo=UTC),
        )
        for date, zone in (
            (datetime(2026, 10, 26), "invalid/zone"),
            (datetime(2026, 3, 8, 2, 30), "America/New_York"),
            (datetime(2026, 11, 1, 1, 30), "America/New_York"),
        ):
            with self.subTest(date=date, zone=zone), self.assertRaises(ValueError):
                launch_time(date, zone)
        aware = datetime.fromisoformat("2026-11-01T01:30:00-04:00")
        self.assertEqual(launch_time(aware, "America/New_York"), aware.astimezone(UTC))

    def test_time_zone_and_dst_validation_without_system_database(self):
        # A fresh interpreter avoids an OS-backed ZoneInfo cache hiding missing data.
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "unittest",
                "test_weather.WeatherTests.test_time_zone_and_dst_validation",
            ],
            cwd=Path(__file__).parent,
            env=dict(os.environ, PYTHONTZPATH=""),
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_request_validation_and_time_window(self):
        for changes in (
            {"latitude": 91},
            {"latitude": True},
            {"elevation": float("nan")},
            {"timezone": "invalid"},
            {"model": "https://localhost"},
            {"elevation_reference": "ellipsoid"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                weather_request(**changes)
        with (
            patch("app.weather._read_json") as read,
            self.assertRaisesRegex(ValueError, "예보 조회"),
        ):
            fetch_weather(weather_request(date=datetime(2000, 1, 1, tzinfo=UTC)))
        read.assert_not_called()

    def test_conversion_temporal_vector_interpolation_and_profile_integrity(self):
        request = weather_request()
        data = response(request)
        data["hourly"]["temperature_2m"] = [10, 20]
        data["hourly"]["wind_direction_10m"] = [350, 10]
        with patch("app.weather._read_json", return_value=(data, "a" * 64)) as read:
            saved = fetch_weather(request)
        self.assertAlmostEqual(saved.levels[0].temperature_k, 288.15)
        self.assertAlmostEqual(saved.levels[0].wind_u_m_s, 0, places=10)
        self.assertLess(saved.levels[0].wind_v_m_s, -9)
        self.assertAlmostEqual(saved.levels[1].wind_u_m_s, -10)
        self.assertGreater(saved.levels[1].altitude_m, 1700)
        endpoint, query = read.call_args.args
        self.assertEqual(endpoint, FORECAST_URL)
        self.assertEqual(query["models"], "gfs_seamless")
        self.assertEqual(query["elevation"], request.elevation)
        self.assertEqual(
            saved.model_dump_json(),
            WeatherProfile.model_validate_json(
                saved.model_dump_json()
            ).model_dump_json(),
        )

    def test_missing_units_nulls_and_wrong_times_fail_closed(self):
        request = weather_request()
        for mutation in ("units", "null", "time", "nan"):
            data = response(request)
            if mutation == "units":
                data["hourly_units"]["wind_speed_10m"] = "km/h"
            if mutation == "null":
                data["hourly"]["temperature_100hPa"][0] = None
            if mutation == "time":
                data["hourly"]["time"][0] = "2000-01-01T00:00"
            if mutation == "nan":
                data["hourly"]["surface_pressure"][0] = float("nan")
            with (
                self.subTest(mutation=mutation),
                patch("app.weather._read_json", return_value=(data, "a" * 64)),
                self.assertRaises(ValueError),
            ):
                fetch_weather(request)

    def test_ellipsoid_offset_and_exact_hour(self):
        request = weather_request(
            elevation_reference="ellipsoid",
            geoid_undulation_m=30,
            date=datetime.now(UTC).replace(hour=3, minute=0, second=0, microsecond=0),
        )
        with patch(
            "app.weather._read_json", return_value=(response(request), "a" * 64)
        ) as read:
            saved = fetch_weather(request)
        self.assertEqual(read.call_args.args[1]["elevation"], 70)
        reference = profile(weather_request(date=request.date))
        self.assertAlmostEqual(
            saved.levels[1].altitude_m - reference.levels[1].altitude_m, 30
        )

    def test_moved_site_time_or_manual_override_rejects_stale_weather(self):
        saved = profile()
        env = environment(saved)
        base = env.model_dump(mode="json")
        for changes in (
            {"latitude": 36},
            {"elevation": 101},
            {"datum": "NAD83"},
            {"date": (saved.request.date + timedelta(hours=1)).isoformat()},
            {"geoid_undulation_m": 30},
            {"wind_u": 1},
            {"atmosphere_type": "standard_atmosphere"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                EnvironmentConfig.model_validate_json(json.dumps(base | changes))

    def test_pad_height_preserves_weather_coverage_at_ground_contact(self):
        saved = profile(weather_request(pad_height_m=2))
        self.assertEqual(saved.levels[0].altitude_m, 98)
        env = build_environment(environment(saved))
        self.assertEqual(env.uarc_weather_bounds[0], 98)
        self.assertAlmostEqual(env.pressure(98), 100000)

    def test_frozen_weather_drives_engine_and_saved_design_offline(self):
        saved = profile()
        env = environment(saved)
        native = build_environment(env)
        self.assertAlmostEqual(native.temperature(100), saved.levels[0].temperature_k)
        self.assertAlmostEqual(native.wind_velocity_y(100), saved.levels[0].wind_v_m_s)
        self.assertAlmostEqual(native.pressure(100), 100000)
        design = RocketDesign.model_validate_json(
            Path("../examples/design.json").read_text()
        )
        design.environment = env
        config, _ = compile_design(design)
        with (
            tempfile.TemporaryDirectory() as directory,
            closing(RunStore(Path(directory))) as storage,
        ):
            record = storage.save_design(design, config)
            restored = RocketDesign.model_validate_json(
                json.dumps(storage.get_saved_design(record["design_id"]))
            )
        with patch(
            "app.weather._read_json", side_effect=AssertionError("network is forbidden")
        ):
            native = build_environment(restored.environment)
        self.assertEqual(restored.environment.weather_profile.response_sha256, "a" * 64)
        self.assertAlmostEqual(native.wind_velocity_x(100), saved.levels[0].wind_u_m_s)

    def test_solver_rejects_flight_outside_weather_coverage(self):
        env = build_environment(environment(profile()))
        rocket = build_rocket(
            None,
            RocketConfig(
                radius=0.025,
                mass=1,
                inertia=(1, 1, 1),
                power_off_drag=0,
                power_on_drag=0,
                center_of_mass_without_motor=0,
            ),
        )
        top = env.uarc_weather_bounds[1]
        with self.assertRaisesRegex(RuntimeError, "기상 자료의 고도 범위"):
            run_simulation(
                rocket,
                env,
                FlightConfig(
                    rail_length=1,
                    inclination=90,
                    heading=0,
                    max_time=0.1,
                    initial_solution=(0, 0, 0, top + 100, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0),
                ),
            )

    def test_search_and_bridge_return_only_validated_results(self):
        _search_places.cache_clear()
        data = {
            "results": [
                dict(
                    id=1,
                    name="울산",
                    latitude=35,
                    longitude=129,
                    admin1="울산",
                    country="대한민국",
                    country_code="KR",
                    timezone="Asia/Seoul",
                )
            ]
        }
        with patch(
            "app.weather._read_json",
            side_effect=lambda url, parameters: (
                {"type": "FeatureCollection", "features": []}
                if url == PLACE_URL
                else data,
                "a" * 64,
            ),
        ) as read:
            places = search_locations(LocationSearch(query=" 울산 "))
            result = DesktopBridge().search_locations('{"query":"울산"}')
        self.assertEqual(places[0].region, "울산, 대한민국")
        self.assertEqual(result[0]["latitude"], 35)
        self.assertEqual(read.call_args.args[0], SEARCH_URL)
        with self.assertRaises(ValidationError):
            DesktopBridge().get_weather('{"latitude":true}')

    def test_network_boundaries_size_redirect_and_error(self):
        class Response(io.BytesIO):
            def geturl(self):
                return SEARCH_URL

        with patch(
            "app.weather._OPENER.open", return_value=Response(b'{"results":[]}')
        ) as opened:
            data, digest = _read_json(SEARCH_URL, {"name": "울산"})
        self.assertEqual(data, {"results": []})
        self.assertEqual(len(digest), 64)
        self.assertEqual(opened.call_args.kwargs["timeout"], 15)
        with (
            patch(
                "app.weather._OPENER.open",
                return_value=Response(b"x" * (256 * 1024 + 1)),
            ),
            self.assertRaisesRegex(ValueError, "256 KiB"),
        ):
            _read_json(SEARCH_URL, {})
        with (
            patch("app.weather._OPENER.open", side_effect=URLError("offline")),
            self.assertRaisesRegex(ValueError, "기존 설정"),
        ):
            _read_json(SEARCH_URL, {})
        with self.assertRaisesRegex(ValueError, "redirects"):
            _NoRedirect().redirect_request(None, None, 302, "", {}, "http://127.0.0.1")


if __name__ == "__main__":
    unittest.main()
