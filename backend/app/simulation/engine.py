"""Assemble validated RocketPy inputs and compute flights without HTTP or storage."""

from collections.abc import Sequence
from copy import deepcopy
from math import isfinite
from typing import Any

import numpy as np
from rocketpy import (
    AeroSurface,
    CylindricalTank,
    EllipticalFins,
    Environment,
    Flight,
    Fluid,
    Function,
    GenericMotor,
    HybridMotor,
    LiquidMotor,
    MassBasedTank,
    Motor,
    NoseCone,
    Rocket,
    SolidMotor,
    Tail,
    Tank,
    TrapezoidalFins,
)

from app.schemas import (
    EnvironmentConfig,
    FlightConfig,
    FlightSummary,
    MotorConfig,
    NoseConeConfig,
    RocketConfig,
    SimulationConfig,
    SurfaceConfig,
)
from app.terrain import GroundSurface, coordinates

MOTOR_TYPES = {
    "solid": SolidMotor,
    "liquid": LiquidMotor,
    "hybrid": HybridMotor,
    "generic": GenericMotor,
}


class _HaackNoseCone(NoseCone):
    """Continuous sharp Haack profile with a volume-based small-angle CP."""

    def __init__(self, config: NoseConeConfig):
        super().__init__(
            length=config.length,
            kind="vonkarman",
            base_radius=config.base_radius,
            rocket_radius=config.rocket_radius,
        )
        length, radius, coefficient = self.length, self.base_radius, config.haack_c

        def profile(x):
            theta = np.arccos(1 - 2 * np.clip(np.asarray(x) / length, 0, 1))
            squared = (
                theta - np.sin(2 * theta) / 2 + coefficient * np.sin(theta) ** 3
            ) / np.pi
            return radius * np.sqrt(np.maximum(squared, 0))

        self._kind = "haack"
        self.haack_c = coefficient
        self.y_nosecone = Function(profile)
        # Barrowman body-of-revolution CP: L - volume / base_area.
        # The Haack volume is base_area * L * (1/2 + 3*C/16).
        self.k = 0.5 - 3 * coefficient / 16
        self.evaluate_center_of_pressure()
        self.evaluate_nose_shape()


def build_surface(config: SurfaceConfig) -> AeroSurface:
    if isinstance(config, NoseConeConfig) and config.kind == "haack":
        return _HaackNoseCone(config)
    surface_types = {
        "nose": NoseCone,
        "trapezoidal_fins": TrapezoidalFins,
        "elliptical_fins": EllipticalFins,
        "tail": Tail,
    }
    return surface_types[config.surface_type](
        **config.model_dump(exclude={"surface_type", "position", "haack_c"})
    )


def build_environment(config: EnvironmentConfig) -> Environment:
    """Create the selected atmosphere; weather/file errors propagate to the caller."""
    env = Environment(
        **config.model_dump(
            include={
                "latitude",
                "longitude",
                "elevation",
                "date",
                "timezone",
                "gravity",
                "datum",
                "max_expected_height",
            }
        )
    )
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
    env.uarc_ground = (
        GroundSurface(config) if config.terrain_mode == "terrain" else None
    )
    return env


def build_motor(
    config: MotorConfig, *, tanks: Sequence[tuple[Tank, float]] = ()
) -> Motor:
    """Create caller-defined hardware, including tanks for liquid/hybrid motors."""
    motor = MOTOR_TYPES[config.motor_type](**config.model_dump(exclude={"motor_type"}))
    if isinstance(motor, (LiquidMotor, HybridMotor)):
        if not tanks:
            raise ValueError("Liquid and hybrid motors require configured tanks.")
        for tank, position in tanks:
            motor.add_tank(deepcopy(tank), position)
    elif tanks:
        raise ValueError("Tanks are supported only for liquid and hybrid motors.")
    return motor


def build_rocket(
    motor: Motor | None,
    config: RocketConfig,
    *,
    surfaces: Sequence[tuple[AeroSurface, float | tuple[float, float, float]]] = (),
) -> Rocket:
    """Assemble the body, positioned surfaces, recovery system, and rail buttons.

    Body mass/inertia exclude the entire motor. Surface positions use the rocket
    frame; motor_position locates the motor frame origin. Additional native
    sensors/controllers/air brakes can be attached to the returned Rocket.
    """
    rocket = Rocket(
        **config.model_dump(
            exclude={
                "motor_position",
                "parachutes",
                "rail_buttons",
            }
        )
    )
    if motor is not None:
        rocket.add_motor(deepcopy(motor), position=config.motor_position)
    for surface, position in surfaces:
        rocket.add_surfaces(deepcopy(surface), position)
    for parachute in config.parachutes:
        rocket.add_parachute(**parachute.model_dump())
    if config.rail_buttons is not None:
        rocket.set_rail_buttons(**config.rail_buttons.model_dump())
    return rocket


def run_simulation(
    rocket: Rocket, environment: Environment, config: FlightConfig
) -> Flight:
    """Compute a complete Flight object using validated launch/solver settings.

    A rocket copy isolates parachute/sensor histories across runs. Stateful user
    callbacks remain the caller's responsibility; do not mutate a shared
    environment during/after a run. max_time is simulated time, not a timeout.
    """
    options = config.model_dump(exclude={"max_time_step"})
    ground = getattr(environment, "uarc_ground", None)
    flight_type = Flight
    extra = {}
    if ground is not None:
        from app.simulation.terrain_flight import TerrainFlight

        flight_type = TerrainFlight
        extra["ground"] = ground
    step = config.max_time_step if config.max_time_step is not None else float("inf")
    flight = flight_type(
        rocket=deepcopy(rocket),
        environment=environment,
        max_time_step=min(step, 0.05) if ground is not None else step,
        **options,
        **extra,
    )
    solution = np.asarray(flight.solution_array, dtype=float)
    if (
        solution.ndim != 2
        or solution.shape[1] != 14
        or len(solution) == 0
        or not np.isfinite(solution).all()
        or np.any(np.diff(solution[:, 0]) < 0)
    ):
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
    solution = np.asarray(flight.solution_array, dtype=float)
    maximum_altitude = _result_number(np.max(solution[:, 3]))
    summary = {
        "name": flight.name,
        "initial_mass_kg": _result_number(flight.rocket.total_mass(flight.t_initial)),
        "final_mass_kg": _result_number(flight.rocket.total_mass(flight.t_final)),
        "initial_center_of_mass_m": _result_number(
            flight.rocket.center_of_mass(flight.t_initial)
        ),
        "final_center_of_mass_m": _result_number(
            flight.rocket.center_of_mass(flight.t_final)
        ),
        "termination_reason": reason,
        "apogee_reached": apogee_reached,
        "landed": landed,
        "start_time_s": _result_number(flight.t_initial),
        "end_time_s": _result_number(flight.t_final),
        "duration_s": _result_number(flight.t_final - flight.t_initial),
        "apogee_asl_m": _result_number(flight.apogee) if apogee_reached else None,
        "apogee_agl_m": _result_number(flight.apogee - flight.env.elevation)
        if apogee_reached
        else None,
        "apogee_time_s": _result_number(flight.apogee_time) if apogee_reached else None,
        "max_altitude_asl_m": maximum_altitude,
        "max_altitude_agl_m": _result_number(maximum_altitude - flight.env.elevation),
        "max_speed_m_s": _result_number(flight.max_speed),
        "max_speed_time_s": _result_number(flight.max_speed_time),
        "impact_x_m": _result_number(flight.x_impact) if landed else None,
        "impact_y_m": _result_number(flight.y_impact) if landed else None,
        "impact_speed_m_s": _result_number(np.linalg.norm(flight.impact_state[3:6]))
        if landed
        else None,
        "ground_model": "terrain"
        if getattr(flight.env, "uarc_ground", None)
        else "flat",
        "impact_elevation_m": _result_number(flight.impact_state[2])
        if landed
        else None,
        "parachute_events": [
            {"name": parachute.name, "trigger_time_s": _result_number(time)}
            for time, parachute in flight.parachute_events
        ],
    }
    if landed and np.hypot(flight.x_impact, flight.y_impact) <= 10_000:
        latitude, longitude = coordinates(
            flight.env.latitude,
            flight.env.longitude,
            flight.x_impact,
            flight.y_impact,
        )
        summary.update(impact_latitude=latitude, impact_longitude=longitude)
    return FlightSummary.model_validate(summary).model_dump(mode="json")


def build_simulation(config: SimulationConfig) -> tuple[Rocket, Environment]:
    """Build all runtime objects locally; only the config crosses processes."""
    tanks = [
        (
            MassBasedTank(
                name=tank.name,
                geometry=CylindricalTank(
                    radius_function=tank.radius,
                    height=tank.height,
                    spherical_caps=tank.spherical_caps,
                ),
                flux_time=tank.flux_time,
                liquid=Fluid(**tank.liquid.model_dump()),
                gas=Fluid(**tank.gas.model_dump()),
                liquid_mass=tank.liquid_mass,
                gas_mass=tank.gas_mass,
                discretize=tank.discretize,
            ),
            tank.position,
        )
        for tank in config.tanks
    ]
    surfaces = [
        (build_surface(surface), surface.position) for surface in config.surfaces
    ]
    motor = build_motor(config.motor, tanks=tanks) if config.motor is not None else None
    return (
        build_rocket(motor, config.rocket, surfaces=surfaces),
        build_environment(config.environment),
    )
