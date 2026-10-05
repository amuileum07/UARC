import unittest
from datetime import datetime, timezone

from rocketpy import Environment

from app.schemas import EnvironmentConfig
from app.simulation.engine import build_environment


class BuildEnvironmentTests(unittest.TestCase):
    def test_standard_atmosphere_and_location(self):
        env = build_environment(EnvironmentConfig(latitude=35.5721, longitude=129.1822, elevation=53))
        self.assertIsInstance(env, Environment)
        self.assertEqual((env.latitude, env.longitude, env.elevation), (35.5721, 129.1822, 53))
        self.assertAlmostEqual(env.pressure(0), 101325)
        self.assertAlmostEqual(env.temperature(0), 288.15)
        self.assertLess(env.pressure(1000), env.pressure(0))
        self.assertEqual(env.wind_velocity_x(53), 0)
        self.assertEqual(env.wind_velocity_y(53), 0)

    def test_custom_weather_retains_unspecified_pressure_profile(self):
        env = build_environment(EnvironmentConfig(
            latitude=35.5721, longitude=129.1822, elevation=53,
            temperature=293.15, wind_u=2.83, wind_v=-2.83,
        ))
        for altitude in (53, 1000):
            self.assertAlmostEqual(env.temperature(altitude), 293.15)
            self.assertAlmostEqual(env.wind_velocity_x(altitude), 2.83)
            self.assertAlmostEqual(env.wind_velocity_y(altitude), -2.83)
        self.assertLess(env.pressure(1000), env.pressure(53))

    def test_custom_pressure_and_gravity(self):
        env = build_environment(EnvironmentConfig(latitude=35.5721, longitude=129.1822, elevation=53, pressure=98000, gravity=9.81))
        for altitude in (53, 1000):
            self.assertAlmostEqual(env.pressure(altitude), 98000)
            self.assertAlmostEqual(env.gravity(altitude), 9.81)
        self.assertLess(env.temperature(1000), env.temperature(53))

    def test_local_dates_are_converted_to_utc(self):
        for date in ((2026, 10, 5, 12), datetime(2026, 10, 5, 12)):
            with self.subTest(date=date):
                env = build_environment(EnvironmentConfig(latitude=35.5721, longitude=129.1822, elevation=53, date=date, timezone="Asia/Seoul"))
                self.assertEqual(env.datetime_date, datetime(2026, 10, 5, 3, tzinfo=timezone.utc))

    def test_invalid_inputs_are_rejected(self):
        for overrides in (
            {"latitude": 91}, {"longitude": -181}, {"latitude": True},
            {"elevation": float("nan")}, {"wind_u": float("inf")},
            {"max_expected_height": 53}, {"gravity": 0},
            {"pressure": -1}, {"temperature": 0}, {"wind_v": [1, 2]},
            {"date": "2026-10-05"}, {"date": (2026, 10, 5)},
            {"date": (2026, 13, 5, 12)},
        ):
            with self.subTest(overrides=overrides):
                args = {"latitude": 35.5721, "longitude": 129.1822, "elevation": 53}
                args.update(overrides)
                with self.assertRaises(ValueError):
                    build_environment(EnvironmentConfig(**args))


if __name__ == "__main__":
    unittest.main()
