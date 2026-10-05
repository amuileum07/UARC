"""Offline integration tests with synthetic hardware, not study-note examples."""

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import numpy as np
from pydantic import TypeAdapter, ValidationError
from rocketpy import (
    CylindricalTank, Flight, Fluid, GenericMotor, HybridMotor, LiquidMotor,
    MassBasedTank, NoseCone, SolidMotor, TrapezoidalFins,
)

from app.schemas import (
    EnvironmentConfig, FlightConfig, GenericMotorConfig, HybridMotorConfig,
    LiquidMotorConfig, MotorConfig, ParachuteConfig, RocketConfig, SolidMotorConfig,
)
from app.simulation.engine import (
    build_environment, build_motor, build_rocket, run_simulation, summarize_flight,
)


def motor_parameters(kind="generic"):
    parameters = dict(
        thrust_source=[(0, 0), (0.05, 60), (0.9, 60), (1, 0)],
        burn_time=1, nozzle_radius=0.01, dry_mass=0.15,
        dry_inertia=(0.001, 0.001, 0.0001),
    )
    if kind == "generic":
        parameters.update(chamber_radius=0.018, chamber_height=0.12,
                          chamber_position=0.07, propellant_initial_mass=0.1)
    else:
        parameters["center_of_dry_mass_position"] = 0.05
    if kind in {"solid", "hybrid"}:
        parameters.update(
            grain_number=1, grain_density=1700, grain_outer_radius=0.02,
            grain_initial_inner_radius=0.008, grain_initial_height=0.1,
            grain_separation=0, grains_center_of_mass_position=0.06,
        )
    return parameters


def tank_fixture():
    volume = np.pi * 0.02**2 * 0.2
    return MassBasedTank(
        name="synthetic tank", geometry=CylindricalTank(radius_function=0.02, height=0.2),
        flux_time=1, liquid=Fluid("test liquid", 1000), gas=Fluid("test gas", 1.2),
        liquid_mass=[(0, 0.08), (1, 0.01)],
        gas_mass=[(0, (volume - 0.08 / 1000) * 1.2), (1, (volume - 0.01 / 1000) * 1.2)],
    )


def rocket_parameters():
    return dict(
        radius=0.025, mass=1.2, inertia=(0.08, 0.08, 0.002),
        power_off_drag=0.5, power_on_drag=0.4, center_of_mass_without_motor=0,
        motor_position=-0.45,
        parachutes=[dict(name="recovery", cd_s=0.3, trigger="apogee", lag=0.1)],
        rail_buttons=dict(upper_button_position=-0.1, lower_button_position=-0.35),
    )


def surface_fixture():
    return [
        (NoseCone(length=0.2, kind="conical", base_radius=0.025), 0.7),
        (TrapezoidalFins(n=4, root_chord=0.12, tip_chord=0.05,
                         span=0.08, rocket_radius=0.025), -0.35),
    ]


class GeneralEngineTests(unittest.TestCase):
    def setUp(self):
        self.environment = build_environment(EnvironmentConfig(latitude=0, longitude=0, elevation=120))
        self.motor = build_motor(GenericMotorConfig(**motor_parameters()))
        self.rocket = build_rocket(
            self.motor, RocketConfig(**rocket_parameters()), surfaces=surface_fixture(),
        )

    def run_flight(self, **options):
        return run_simulation(self.rocket, self.environment, FlightConfig(
            rail_length=1.5, inclination=85, heading=0, max_time_step=0.05, **options
        ))

    def test_full_flight_matches_native_rocketpy(self):
        flight = self.run_flight()
        expected = Flight(deepcopy(self.rocket), self.environment, 1.5,
                          inclination=85, heading=0, max_time_step=0.05)
        self.assertAlmostEqual(flight.apogee, expected.apogee, places=8)
        self.assertAlmostEqual(flight.t_final, expected.t_final, places=8)
        summary = summarize_flight(flight)
        self.assertEqual(summary["termination_reason"], "impact")
        self.assertTrue(summary["landed"])
        self.assertGreater(summary["apogee_agl_m"], 0)
        self.assertAlmostEqual(summary["apogee_asl_m"] - summary["apogee_agl_m"], 120)
        self.assertGreater(summary["impact_speed_m_s"], 0)
        self.assertEqual(summary["parachute_events"][0]["name"], "recovery")
        self.assertEqual(self.rocket.parachutes[0].clean_pressure_signal, [])
        json.dumps(summary, allow_nan=False)

    def test_time_limit_does_not_report_unreached_events(self):
        summary = summarize_flight(self.run_flight(max_time=0.1))
        self.assertEqual(summary["termination_reason"], "time_limit")
        self.assertFalse(summary["apogee_reached"])
        self.assertIsNone(summary["apogee_agl_m"])
        self.assertIsNone(summary["apogee_time_s"])
        self.assertIsNone(summary["impact_speed_m_s"])
        self.assertAlmostEqual(summary["duration_s"], 0.1)
        json.dumps(summary, allow_nan=False)

    def test_apogee_stop_and_repeat_runs_keep_history(self):
        first = self.run_flight()
        history = list(first.rocket.parachutes[0].clean_pressure_signal)
        second = self.run_flight(terminate_on_apogee=True)
        self.assertEqual(first.rocket.parachutes[0].clean_pressure_signal, history)
        summary = summarize_flight(second)
        self.assertEqual(summary["termination_reason"], "apogee")
        self.assertFalse(summary["landed"])
        self.assertAlmostEqual(summary["end_time_s"], summary["apogee_time_s"])

    def test_caller_parameters_change_the_simulation(self):
        baseline = self.run_flight(terminate_on_apogee=True)
        parameters = rocket_parameters()
        parameters["mass"] = 1.6
        heavier = build_rocket(self.motor, RocketConfig(**parameters), surfaces=surface_fixture())
        changed = run_simulation(heavier, self.environment, FlightConfig(
            rail_length=1.5, inclination=85, heading=0, terminate_on_apogee=True
        ))
        self.assertLess(changed.apogee, baseline.apogee)

    def test_all_motor_types_can_fly(self):
        for kind, model, expected in (
            ("generic", GenericMotorConfig, GenericMotor),
            ("solid", SolidMotorConfig, SolidMotor),
            ("liquid", LiquidMotorConfig, LiquidMotor),
            ("hybrid", HybridMotorConfig, HybridMotor),
        ):
            with self.subTest(kind=kind):
                tanks = [(tank_fixture(), 0.1)] if kind in {"liquid", "hybrid"} else []
                config = model(**motor_parameters(kind))
                motor = build_motor(config, tanks=tanks)
                self.assertIsInstance(motor, expected)
                self.assertEqual(config.model_dump_json(), model.model_validate_json(config.model_dump_json()).model_dump_json())
                rocket = build_rocket(motor, RocketConfig(**rocket_parameters()), surfaces=surface_fixture())
                flight = run_simulation(rocket, self.environment, FlightConfig(
                    rail_length=1.5, inclination=85, heading=0, terminate_on_apogee=True
                ))
                self.assertTrue(summarize_flight(flight)["apogee_reached"])

    def test_resume_uses_the_previous_flights_final_state(self):
        partial = self.run_flight(max_time=0.5)
        resumed = self.run_flight(
            initial_solution=tuple(partial.solution[-1]), terminate_on_apogee=True,
        )
        self.assertEqual(resumed.t_initial, partial.t_final)
        np.testing.assert_allclose(resumed.solution[0], partial.solution[-1])
        self.assertEqual(summarize_flight(resumed)["termination_reason"], "apogee")

    def test_weather_profiles_and_file_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wind.csv"
            path.write_text("0,0\n1000,10\n")
            env = build_environment(EnvironmentConfig(
                latitude=0, longitude=0, elevation=120, wind_u=str(path),
                temperature=[(0, 290), (1000, 280)],
            ))
            self.assertAlmostEqual(env.wind_velocity_x(500), 5)
            self.assertAlmostEqual(env.temperature(500), 285)
            self.assertLess(env.pressure(1000), env.pressure(0))
        with self.assertRaisesRegex(ValueError, "Could not read") as error:
            build_environment(EnvironmentConfig(latitude=0, longitude=0, elevation=0, wind_u=str(path)))
        self.assertIsInstance(error.exception.__cause__, FileNotFoundError)
        with self.assertRaises(ValueError):
            build_environment(EnvironmentConfig(latitude=0, longitude=0, elevation=0, wind_u=[(1000, 0), (0, 10)]))

    def test_external_weather_forwarding_and_failures(self):
        with patch("app.simulation.engine.Environment.set_atmospheric_model", autospec=True) as load:
            build_environment(EnvironmentConfig(
                latitude=0, longitude=0, elevation=120, date=(2026, 10, 5, 12),
                atmosphere_type="forecast", atmosphere_file="GFS",
            ))
            self.assertEqual(load.call_args.kwargs["type"], "forecast")
            self.assertEqual(load.call_args.kwargs["file"], "GFS")
        with patch("app.simulation.engine.Environment.process_forecast_reanalysis",
                   side_effect=OSError("weather unavailable")):
            with self.assertRaisesRegex(OSError, "weather unavailable"):
                build_environment(EnvironmentConfig(
                    latitude=0, longitude=0, elevation=120, date=(2026, 10, 5, 12),
                    atmosphere_type="reanalysis", atmosphere_file="weather.nc",
                    atmosphere_dictionary="ECMWF",
                ))
        with self.assertRaises(ValueError):
            build_environment(EnvironmentConfig(latitude=0, longitude=0, elevation=120, atmosphere_type="forecast", atmosphere_file="GFS"))
        with self.assertRaises(ValueError):
            build_environment(EnvironmentConfig(latitude=0, longitude=0, elevation=120, atmosphere_type="standard_atmosphere", wind_u=2))

    def test_invalid_hardware_and_execution_settings(self):
        for settings in ({"rail_length": 0}, {"inclination": 0}, {"heading": float("nan")},
                         {"max_time": 0}, {"max_time_step": 0}, {"rtol": -1},
                         {"initial_solution": [0] * 14}):
            with self.subTest(settings=settings):
                args = dict(rail_length=1.5, inclination=85, heading=0)
                args.update(settings)
                with self.assertRaises(ValueError):
                    run_simulation(self.rocket, self.environment, FlightConfig(**args))
        for settings in ({"radius": -1}, {"inertia": (1, 1, 4)},
                         {"power_off_drag": float("nan")},
                         {"parachutes": [dict(name="bad", cd_s=1, trigger="apogee", sampling_rate=0)]}):
            with self.subTest(settings=settings):
                args = rocket_parameters()
                args.update(settings)
                with self.assertRaises(ValueError):
                    build_rocket(self.motor, RocketConfig(**args))
        with self.assertRaises(ValueError):
            build_motor(LiquidMotorConfig(**motor_parameters("liquid")))
        with self.assertRaises(ValueError):
            build_motor(GenericMotorConfig(**motor_parameters()), tanks=[(tank_fixture(), 0.1)])
        with self.assertRaises(ValueError):
            build_motor(GenericMotorConfig(**{
                **motor_parameters(), "misspelled_parameter": 1,
            }))

    def test_schema_errors_identify_input_fields_before_computation(self):
        with self.assertRaises(ValidationError) as error:
            RocketConfig(**{**rocket_parameters(), "radius": -1})
        self.assertEqual(error.exception.errors()[0]["loc"], ("radius",))
        for overrides in ({"chamber_height": None}, {"grain_number": 1}):
            with self.subTest(overrides=overrides), self.assertRaises(ValidationError):
                GenericMotorConfig(**{
                    **motor_parameters(), **overrides,
                })
        parameters = motor_parameters()
        del parameters["chamber_radius"]
        with self.assertRaises(ValidationError):
            GenericMotorConfig(**parameters)

    def test_omitted_motor_parameters_keep_native_defaults(self):
        parameters = motor_parameters()
        del parameters["dry_inertia"]
        motor = build_motor(GenericMotorConfig(**parameters))
        self.assertEqual(motor.dry_I_11, 0)
        self.assertEqual(motor.dry_I_22, 0)
        self.assertEqual(motor.dry_I_33, 0)

    def test_schemas_round_trip_as_json_and_expose_json_schema(self):
        configs = [
            EnvironmentConfig(latitude=0, longitude=0, elevation=120,
                              date=(2026, 10, 5, 12), wind_u=[(0, 0), (1000, 10)]),
            RocketConfig(**rocket_parameters()),
            FlightConfig(rail_length=1.5, inclination=85, heading=0),
        ]
        for config in configs:
            with self.subTest(model=type(config).__name__):
                encoded = config.model_dump_json()
                restored = type(config).model_validate_json(encoded)
                self.assertEqual(encoded, restored.model_dump_json())
                json.dumps(type(config).model_json_schema(), allow_nan=False)
        adapter = TypeAdapter(MotorConfig)
        config = GenericMotorConfig(**motor_parameters())
        self.assertIsInstance(adapter.validate_json(config.model_dump_json()), GenericMotorConfig)
        self.assertEqual(adapter.json_schema()["discriminator"]["propertyName"], "motor_type")

    def test_runtime_objects_are_not_accepted_as_dto_fields(self):
        with self.assertRaises(ValidationError):
            RocketConfig(**rocket_parameters(), surfaces=surface_fixture())
        with self.assertRaises(ValidationError):
            EnvironmentConfig(latitude=0, longitude=0, elevation=0, wind_u=lambda h: h / 100)
        with self.assertRaises(ValidationError):
            FlightConfig(rail_length=1.5, inclination=85, heading=0, initial_solution=self.run_flight(max_time=0.1))
        with self.assertRaises(ValidationError):
            ParachuteConfig(name="custom", cd_s=0.3, trigger=lambda *args: False)

    def test_invalid_solver_results_are_not_exposed_as_success(self):
        with patch("app.simulation.engine.Flight") as flight_class:
            flight_class.return_value.solution = [[float("nan")] * 14]
            with self.assertRaisesRegex(RuntimeError, "invalid flight solution"):
                self.run_flight()


if __name__ == "__main__":
    unittest.main()
