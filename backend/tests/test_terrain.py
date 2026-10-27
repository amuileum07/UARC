"""Offline terrain references, acquisition boundaries, and ground-contact integration."""

import io
import json
import unittest
from math import sqrt
from unittest.mock import patch

import numpy as np
from pydantic import ValidationError

from app.schemas import (
    EnvironmentConfig,
    FlightConfig,
    RocketConfig,
    TerrainGrid,
    TerrainRequest,
)
from app.simulation.engine import (
    build_environment,
    build_rocket,
    run_simulation,
    summarize_flight,
)
from app.terrain import (
    GroundSurface,
    check_elevation,
    coordinates,
    fetch_terrain,
    sample_grid,
)


def grid(level=120.0):
    return TerrainGrid(
        south=-0.01,
        north=0.01,
        west=-0.01,
        east=0.01,
        heights=[[level, level], [level, level]],
        reference="EGM96",
        source="Synthetic test plane",
        source_resolution_m=90,
        sampling_distance_m=100,
    )


def environment(terrain, **kwargs):
    return EnvironmentConfig(
        latitude=0,
        longitude=0,
        elevation=120,
        datum="WGS84",
        elevation_reference="EGM96",
        terrain=terrain,
        terrain_mode="terrain",
        gravity=9.81,
        **kwargs,
    )


def ballistic(env, *, north_speed=10, altitude=170, vertical_speed=20, max_time=15):
    rocket = build_rocket(
        None,
        RocketConfig(
            radius=0.025,
            mass=1.2,
            inertia=(0.08, 0.08, 0.002),
            power_off_drag=0,
            power_on_drag=0,
            center_of_mass_without_motor=0,
        ),
    )
    return run_simulation(
        rocket,
        build_environment(env),
        FlightConfig(
            rail_length=1,
            inclination=90,
            heading=0,
            max_time=max_time,
            max_time_step=0.05,
            rtol=1e-9,
            atol=1e-9,
            initial_solution=(
                0,
                0,
                0,
                altitude,
                0,
                north_speed,
                vertical_speed,
                1,
                0,
                0,
                0,
                0,
                0,
                0,
            ),
        ),
    )


class TerrainTests(unittest.TestCase):
    def test_automatic_launch_height_requires_matching_terrain_and_keeps_legacy_manual(
        self,
    ):
        config = environment(grid(118), pad_height_m=2)
        self.assertEqual(config.elevation_mode, "manual")
        self.assertEqual(build_environment(config).elevation, 120)
        config.elevation_mode = "terrain"
        self.assertEqual(build_environment(config).elevation, 120)
        restored = EnvironmentConfig.model_validate_json(config.model_dump_json())
        self.assertEqual(restored.elevation_mode, "terrain")
        for changes in (
            {"terrain": None, "terrain_mode": "flat"},
            {"elevation": 121},
            {"elevation_reference": "unknown"},
            {"datum": "NAD83"},
            {"terrain": grid(119)},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                build_environment(config.model_copy(update=changes))
        config.elevation_mode = "manual"
        config.elevation = 150
        self.assertEqual(build_environment(config).elevation, 150)

    def test_grid_interpolation_bounds_nodata_and_round_trip(self):
        terrain = grid()
        terrain.heights = [[0.0, 10.0], [20.0, 30.0]]
        self.assertAlmostEqual(sample_grid(terrain, 0, 0), 15)
        self.assertEqual(sample_grid(terrain, 0.01, 0.01), 30)
        self.assertEqual(
            TerrainGrid.model_validate_json(terrain.model_dump_json()), terrain
        )
        with self.assertRaises(ValueError):
            sample_grid(terrain, 0.02, 0)
        terrain.heights[0][0] = None
        with self.assertRaises(ValueError):
            sample_grid(terrain, 0, 0)
        with self.assertRaises(ValidationError):
            TerrainGrid.model_validate_json(
                terrain.model_dump_json().replace("null", '"not a height"')
            )

    def test_coordinate_origin_cardinals_and_range(self):
        self.assertEqual(coordinates(35, 129, 0, 0), (35.0, 129.0))
        lat, lon = coordinates(35, 129, 100, 0)
        self.assertGreater(lon, 129)
        self.assertAlmostEqual(lat, 35, places=6)
        lat, lon = coordinates(35, 129, 0, 100)
        self.assertGreater(lat, 35)
        self.assertAlmostEqual(lon, 129)
        with self.assertRaises(ValueError):
            coordinates(0, 0, 10001, 0)

    def test_elevation_reference_pad_and_no_silent_correction(self):
        env = environment(grid(118), pad_height_m=2)
        self.assertEqual(check_elevation(env)["status"], "ok")
        env.elevation_tolerance_m = 1
        env.pad_height_m = 0
        self.assertEqual(check_elevation(env)["status"], "warning")
        self.assertEqual(env.elevation, 120)
        env.elevation_reference = "unknown"
        self.assertEqual(check_elevation(env)["status"], "unverified")
        env.elevation_reference = "ellipsoid"
        env.geoid_undulation_m = 2
        self.assertEqual(GroundSurface(env).at(0, 0), 120)
        env.geoid_undulation_m = None
        self.assertEqual(check_elevation(env)["status"], "unverified")

    def test_flat_terrain_matches_native_impact(self):
        config = environment(grid())
        terrain_flight = ballistic(config)
        config.terrain_mode = "flat"
        flat_flight = ballistic(config)
        # Native impact uses cubic interpolation; allow 1 ms against dense roots.
        self.assertAlmostEqual(terrain_flight.t_final, flat_flight.t_final, delta=0.001)
        self.assertAlmostEqual(terrain_flight.z_impact, 120, places=6)
        np.testing.assert_allclose(
            terrain_flight.impact_state[:6], flat_flight.impact_state[:6], atol=0.02
        )

    def test_valley_continues_below_launch_elevation(self):
        flight = ballistic(environment(grid(80)))
        expected = (20 + sqrt(20**2 + 2 * 9.81 * 90)) / 9.81
        self.assertAlmostEqual(flight.t_final, expected, places=4)
        self.assertAlmostEqual(flight.z_impact, 80, places=6)
        summary = summarize_flight(flight)
        self.assertTrue(summary["landed"])
        self.assertEqual(summary["ground_model"], "terrain")
        self.assertAlmostEqual(summary["impact_elevation_m"], 80)
        self.assertGreater(summary["impact_latitude"], 0)
        self.assertAlmostEqual(flight.env.elevation, 120)

    def test_slope_contact_matches_surface_and_ballistic_reference(self):
        terrain = grid()
        terrain.heights = [[0.0, 0.0], [240.0, 240.0]]
        config = environment(terrain)
        flight = ballistic(config)
        ground = GroundSurface(config)
        self.assertAlmostEqual(
            flight.z_impact, ground.at(flight.x_impact, flight.y_impact), places=6
        )
        self.assertAlmostEqual(
            flight.z_impact,
            170 + 20 * flight.t_final - 9.81 * flight.t_final**2 / 2,
            places=3,
        )
        self.assertGreater(flight.z_impact, 120)

    def test_liftoff_is_not_an_immediate_ground_contact(self):
        flight = ballistic(environment(grid()), altitude=120)
        self.assertGreater(flight.t_final, 4)
        self.assertAlmostEqual(flight.z_impact, 120, places=6)

    def test_time_stop_is_not_landing_and_missing_coverage_fails(self):
        flight = ballistic(environment(grid()), max_time=1)
        self.assertFalse(summarize_flight(flight)["landed"])
        terrain = grid()
        terrain.heights[1][1] = None
        with self.assertRaises(ValueError):
            ballistic(environment(terrain))
        with (
            patch("app.simulation.terrain_flight.version", return_value="1.14.0"),
            self.assertRaises(RuntimeError),
        ):
            ballistic(environment(grid()))

    def test_fetch_is_bounded_and_checks_service_coordinates(self):
        request = TerrainRequest(latitude=0, longitude=0, provider="opentopodata")
        points = []

        def respond(req, timeout):
            from urllib.parse import parse_qs, urlsplit

            locations = parse_qs(urlsplit(req.full_url).query)["locations"][0].split(
                "|"
            )
            points.extend(locations)
            values = [
                {
                    "elevation": 123.0,
                    "location": {
                        "lat": float(p.split(",")[0]),
                        "lng": float(p.split(",")[1]),
                    },
                }
                for p in locations
            ]
            response = io.BytesIO(
                json.dumps({"status": "OK", "results": values}).encode()
            )
            response.geturl = lambda: req.full_url
            return response

        with (
            patch("app.terrain.urlopen", side_effect=respond),
            patch("app.terrain._LAST_FETCH", 0),
        ):
            result = fetch_terrain(request)
        self.assertEqual(len(points), 81)
        self.assertEqual(result.heights[0][0], 123)
        self.assertIn("SHA256", result.source)
        with patch(
            "app.terrain.urlopen", return_value=io.BytesIO(b"x" * (128 * 1024 + 1))
        ) as mocked:
            mocked.return_value.geturl = lambda: (
                "https://api.opentopodata.org/v1/srtm90m"
            )
            with patch("app.terrain._LAST_FETCH", 0), self.assertRaises(ValueError):
                fetch_terrain(request)


if __name__ == "__main__":
    unittest.main()
