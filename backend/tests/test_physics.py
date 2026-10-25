"""An independent trajectory reference with an analytic solution."""

import unittest

import numpy as np

from app.schemas import EnvironmentConfig, FlightConfig, RocketConfig
from app.simulation.engine import (
    build_environment,
    build_rocket,
    run_simulation,
    summarize_flight,
)


class BallisticReferenceTests(unittest.TestCase):
    def test_zero_drag_unpowered_flight_matches_constant_gravity(self):
        gravity, altitude, speed = 9.81, 170.0, 20.0
        # At the pole, vertical velocity is parallel to Earth's rotation axis,
        # so Coriolis acceleration vanishes for this analytic reference.
        environment = build_environment(
            EnvironmentConfig(latitude=90, longitude=0, elevation=120, gravity=gravity)
        )
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
        config = FlightConfig(
            rail_length=1,
            inclination=90,
            heading=0,
            max_time=5,
            max_time_step=0.05,
            rtol=1e-9,
            atol=1e-9,
            initial_solution=(0, 0, 0, altitude, 0, 0, speed, 1, 0, 0, 0, 0, 0, 0),
        )
        flight = run_simulation(rocket, environment, config)
        solution = flight.solution_array
        time = solution[:, 0]
        # With no thrust or aerodynamic surfaces/drag, z''=-g has this exact
        # solution. It independently checks ASL coordinates, velocity, and time.
        np.testing.assert_allclose(
            solution[:, 3],
            altitude + speed * time - gravity * time**2 / 2,
            rtol=0,
            atol=1e-5,
        )
        np.testing.assert_allclose(
            solution[:, 6], speed - gravity * time, rtol=0, atol=1e-6
        )
        summary = summarize_flight(flight)
        self.assertAlmostEqual(summary["apogee_time_s"], speed / gravity, places=5)
        self.assertAlmostEqual(
            summary["apogee_asl_m"], altitude + speed**2 / (2 * gravity), places=5
        )
        self.assertAlmostEqual(summary["apogee_agl_m"], summary["apogee_asl_m"] - 120)
        self.assertEqual(summary["initial_mass_kg"], summary["final_mass_kg"])
        self.assertEqual(summary["termination_reason"], "time_limit")


if __name__ == "__main__":
    unittest.main()
