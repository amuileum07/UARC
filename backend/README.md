# Simulation engine

`app/simulation/engine.py` assembles caller-supplied RocketPy models and runs a
single flight. It contains no preset rocket, motor, launch location, or data-file
path. All quantities use SI units; launch angles use degrees.

| Function | Inputs | Result |
| --- | --- | --- |
| `build_environment` | `EnvironmentConfig` | `Environment` |
| `build_motor` | `MotorConfig` (`solid`, `liquid`, `hybrid`, or `generic`) | `Motor` |
| `build_rocket` | Motor and `RocketConfig` | `Rocket` |
| `run_simulation` | Rocket, environment, and `FlightConfig` | `Flight` |
| `summarize_flight` | A computed `Flight` | Dictionary of numbers, flags, strings, and nullable event values |

The complete `Flight` remains available for RocketPy's plots, telemetry, and
exporters. `run_simulation` returns this object, not the summary dictionary.
The engine performs synchronous computation; scheduling and file storage belong
to the calling application.

`app/schemas.py` validates types, ranges, curves, and relationships between input
values when a configuration is created. Invalid input raises Pydantic's
`ValidationError` before reaching the engine. The engine handles assembly and
computation; errors while loading files/weather or solving a flight propagate to
its caller. These are Python configuration models: native surfaces, tanks, and
callbacks are not directly suitable for JSON API request bodies.

## Example

Run from the `backend/` directory using the project's Python environment.
These synthetic values demonstrate the interface and do not represent real
hardware. Production inputs must come from the vehicle being modeled.

```python
from rocketpy import NoseCone, TrapezoidalFins
from app.schemas import (
    EnvironmentConfig, FlightConfig, MotorConfig, MotorParameters, RocketConfig,
)
from app.simulation.engine import (
    build_environment, build_motor, build_rocket,
    run_simulation, summarize_flight,
)

environment = build_environment(EnvironmentConfig(
    latitude=0, longitude=0, elevation=120,
))
motor = build_motor(MotorConfig(
    motor_type="generic",
    parameters=MotorParameters(
        thrust_source=[(0, 0), (0.05, 60), (0.9, 60), (1, 0)],
        burn_time=1,
        chamber_radius=0.018,
        chamber_height=0.12,
        chamber_position=0.07,
        propellant_initial_mass=0.1,
        nozzle_radius=0.01,
        dry_mass=0.15,
        dry_inertia=(0.001, 0.001, 0.0001),
    ),
))
rocket = build_rocket(motor, RocketConfig(
    radius=0.025,
    mass=1.2,
    inertia=(0.08, 0.08, 0.002),
    power_off_drag=0.5,
    power_on_drag=0.4,
    center_of_mass_without_motor=0,
    motor_position=-0.45,
    surfaces=[
        (NoseCone(length=0.2, kind="conical", base_radius=0.025), 0.7),
        (TrapezoidalFins(n=4, root_chord=0.12, tip_chord=0.05,
                         span=0.08, rocket_radius=0.025), -0.35),
    ],
    parachutes=[dict(name="recovery", cd_s=0.3, trigger="apogee", lag=0.1)],
))
flight = run_simulation(rocket, environment, FlightConfig(
    rail_length=1.5, inclination=85, heading=0,
    max_time=60, max_time_step=0.05,
))
summary = summarize_flight(flight)
print(summary)
```

## Input and result conventions

- `MotorConfig.parameters` accepts `MotorParameters` or a dictionary with native
  constructor keyword names. Only explicitly supplied fields are forwarded;
  omitted options retain the selected RocketPy class's defaults. Required and
  incompatible fields are checked against that class's constructor.
- Body mass and inertia exclude the entire motor. Body positions share the
  rocket coordinate system; `motor_position` locates the motor coordinate origin.
  Motor/tank positions use the motor's own coordinate system.
- `surfaces` accepts `(AeroSurface, position)` pairs, including native nose, fin,
  tail, and custom surfaces. Positions can be axial scalars or `(x, y, z)` tuples.
  `parachutes` and `rail_buttons` use native `Rocket.add_parachute` and
  `Rocket.set_rail_buttons` keyword names. Additional sensors, air brakes, or
  controllers can be attached through RocketPy before running the flight.
- Liquid/hybrid motor construction requires `tanks=[(tank, position), ...]` with
  configured RocketPy `Tank` objects. Solid/generic motors do not accept tanks.
- Numeric curves accept constants, increasing two-column tables, local files,
  callables, or RocketPy `Function` objects. Files/callables are trusted Python
  inputs, not serialized web requests. File errors and solver failures propagate.
- Environment profile heights are ASL meters. Pressure is Pa, temperature K,
  `wind_u` points east, and `wind_v` north. Scalars apply at every altitude.
  Omitted pressure/temperature retain ISA profiles. Weather models may adjust
  RocketPy's `max_expected_height` when loading their data.
- With no `atmosphere_type`, weather overrides select `custom_atmosphere`;
  otherwise the default is `standard_atmosphere`. Explicit external models use
  `atmosphere_type`, `atmosphere_file`, `atmosphere_dictionary`, and optionally
  `pressure_conversion_factor`. Forecast/reanalysis/ensemble/Windy require a
  date. `ensemble_member` selects a loaded ensemble member. Network failures do
  not silently fall back to ISA. Live weather service availability is external.
- `inclination` is relative to the horizontal: 90 degrees is vertical. `heading`
  is clockwise from north and is normalized modulo 360. Standard rail launches
  use an inclination in `(0, 90]`. `initial_solution` can instead supply a native
  14-value state or a previous `Flight`; `max_time` must exceed its start time.
- Flight options such as `terminate_on_apogee`, `rtol`, `atol`, `ode_solver`, and
  `simulation_mode` pass to RocketPy. `max_time` is simulated time, not a server
  timeout. Each run copies the rocket to isolate mutable histories; callers must
  manage state in their own callbacks and avoid mutating a shared environment.
- Summary apogee/impact fields are `None` until their events occur. AGL is relative
  to the launch site's elevation. `max_*` values cover only the simulated interval.
  `termination_reason` is `impact`, `apogee`, `time_limit`, or `stopped`.
  `impact_speed_m_s` is the full velocity magnitude, not signed vertical velocity.

## Verification

```bash
cd backend
.venv/bin/python -m unittest discover -s tests -v
```

Tests use synthetic hardware and offline weather. They compare actual flight
results with native RocketPy, exercise all four motor types, and check early
termination, recovery, repeated runs, profiles, validation, and weather errors.
External weather forwarding is mocked; it does not verify live forecast services.
