"""Assemble validated RocketPy inputs and compute flights without HTTP or storage."""

from copy import deepcopy
from math import isfinite
from typing import Any

import numpy as np
from rocketpy import Environment, Flight, HybridMotor, LiquidMotor, Motor, Rocket

from app.schemas import EnvironmentConfig, FlightConfig, MOTOR_TYPES, MotorConfig, RocketConfig


def build_environment(config: EnvironmentConfig) -> Environment:
    """Create the selected atmosphere; weather/file errors propagate to the caller."""
    env = Environment(**config.model_dump(include={
        "latitude", "longitude", "elevation", "date", "timezone", "gravity",
        "datum", "max_expected_height",
    }))
    if config.atmosphere_type != "standard_atmosphere":
        env.set_atmospheric_model(
            type=config.atmosphere_type,
            file=config.atmosphere_file,
            dictionary=config.atmosphere_dictionary,
            pressure=config.pressure,
            temperature=config.temperature,
            wind_u=config.wind_u,
            wind_v=config.wind_v,
            pressure_conversion_factor=config.pressure_conversion_factor,
        )
    if config.atmosphere_type == "ensemble":
        env.select_ensemble_member(config.ensemble_member)
    return env


def build_motor(config: MotorConfig) -> Motor:
    """Create caller-defined hardware, including tanks for liquid/hybrid motors."""
    motor = MOTOR_TYPES[config.motor_type](**config.parameters.model_dump(exclude_unset=True))
    if isinstance(motor, (LiquidMotor, HybridMotor)):
        for tank, position in config.tanks:
            motor.add_tank(deepcopy(tank), position)
    return motor


def build_rocket(motor: Motor | None, config: RocketConfig) -> Rocket:
    """Assemble the body, positioned surfaces, recovery system, and rail buttons.

    Body mass/inertia exclude the entire motor. Surface positions use the rocket
    frame; motor_position locates the motor frame origin. Additional native
    sensors/controllers/air brakes can be attached to the returned Rocket.
    """
    rocket = Rocket(**config.model_dump(exclude={
        "motor_position", "surfaces", "parachutes", "rail_buttons",
    }))
    if motor is not None:
        rocket.add_motor(deepcopy(motor), position=config.motor_position)
    for surface, position in config.surfaces:
        rocket.add_surfaces(deepcopy(surface), position)
    for parachute in config.parachutes:
        rocket.add_parachute(**parachute.model_dump())
    if config.rail_buttons is not None:
        rocket.set_rail_buttons(**config.rail_buttons.model_dump())
    return rocket


def run_simulation(rocket: Rocket, environment: Environment, config: FlightConfig) -> Flight:
    """Compute a complete Flight object using validated launch/solver settings.

    A rocket copy isolates parachute/sensor histories across runs. Stateful user
    callbacks remain the caller's responsibility; do not mutate a shared
    environment during/after a run. max_time is simulated time, not a timeout.
    """
    if not isinstance(rocket, Rocket) or not isinstance(environment, Environment):
        raise TypeError("rocket and environment must be RocketPy objects.")
    flight = Flight(rocket=deepcopy(rocket), environment=environment, **config.model_dump())
    solution = np.asarray(flight.solution, dtype=float)
    if solution.ndim != 2 or solution.shape[1] != 14 or not np.isfinite(solution).all():
        raise RuntimeError("RocketPy returned an invalid flight solution.")
    return flight


def _result_number(value: Any) -> float:
    number = float(value)
    if not isfinite(number):
        raise RuntimeError("RocketPy returned a non-finite result.")
    return number


def summarize_flight(flight: Flight) -> dict[str, Any]:
    """Extract JSON-compatible metrics for the simulated interval only.

    Missing apogee/impact events are None, not RocketPy's zero sentinels. ASL
    refers to sea level; AGL is relative to the environment's launch elevation.
    """
    apogee_reached = len(flight.apogee_state) > 1
    landed = len(flight.impact_state) > 1
    if landed:
        reason = "impact"
    elif apogee_reached and flight.terminate_on_apogee:
        reason = "apogee"
    elif np.isclose(flight.t_final, flight.max_time, rtol=0, atol=1e-6):
        reason = "time_limit"
    else:
        reason = "stopped"
    solution = np.asarray(flight.solution, dtype=float)
    maximum_altitude = _result_number(np.max(solution[:, 3]))
    return {
        "name": flight.name,
        "termination_reason": reason,
        "apogee_reached": apogee_reached,
        "landed": landed,
        "start_time_s": _result_number(flight.t_initial),
        "end_time_s": _result_number(flight.t_final),
        "duration_s": _result_number(flight.t_final - flight.t_initial),
        "apogee_asl_m": _result_number(flight.apogee) if apogee_reached else None,
        "apogee_agl_m": _result_number(flight.apogee - flight.env.elevation) if apogee_reached else None,
        "apogee_time_s": _result_number(flight.apogee_time) if apogee_reached else None,
        "max_altitude_asl_m": maximum_altitude,
        "max_altitude_agl_m": _result_number(maximum_altitude - flight.env.elevation),
        "max_speed_m_s": _result_number(flight.max_speed),
        "max_speed_time_s": _result_number(flight.max_speed_time),
        "impact_x_m": _result_number(flight.x_impact) if landed else None,
        "impact_y_m": _result_number(flight.y_impact) if landed else None,
        "impact_speed_m_s": _result_number(np.linalg.norm(flight.impact_state[3:6])) if landed else None,
        "parachute_events": [
            {"name": parachute.name, "trigger_time_s": _result_number(time)}
            for time, parachute in flight.parachute_events
        ],
    }
