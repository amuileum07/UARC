"""Solver settings, assembled simulation inputs, execution records, and results."""

from math import isclose
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from .common import EngineConfig, NonNegative, Number, Positive, Tolerance
from .environment import EnvironmentConfig
from .propulsion import (
    HybridMotorConfig,
    LiquidMotorConfig,
    MassBasedTankConfig,
    MotorConfig,
)
from .rocket import RocketConfig, SurfaceConfig


class FlightConfig(EngineConfig):
    rail_length: Positive
    inclination: Number
    heading: Number
    initial_solution: (
        Annotated[tuple[Number, ...], Field(min_length=14, max_length=14)] | None
    ) = None
    terminate_on_apogee: bool = False
    max_time: Positive = 600.0
    # None means no upper step limit; unlike infinity, it round-trips through JSON.
    max_time_step: Positive | None = None
    min_time_step: NonNegative = 0.0
    rtol: Tolerance = 1e-6
    atol: Tolerance | None = None
    time_overshoot: bool = True
    verbose: bool = False
    name: str = "Flight"
    equations_of_motion: Literal["standard", "solid_propulsion"] = "standard"
    ode_solver: Literal["LSODA", "RK23", "RK45", "DOP853", "Radau", "BDF"] = "LSODA"
    simulation_mode: Literal["6 DOF", "3 DOF"] = "6 DOF"

    @model_validator(mode="after")
    def consistent_flight(self):
        self.heading %= 360
        start = 0.0
        if self.initial_solution is None:
            if not 0 < self.inclination <= 90:
                raise ValueError("Rail launch inclination must be in (0, 90] degrees.")
        else:
            state = self.initial_solution
            if not isclose(sum(v * v for v in state[7:11]), 1, rel_tol=0, abs_tol=1e-6):
                raise ValueError("initial_solution needs a unit attitude quaternion.")
            start = state[0]
        if self.max_time <= start:
            raise ValueError("max_time must be later than the initial simulation time.")
        if self.max_time_step is not None and self.min_time_step > self.max_time_step:
            raise ValueError("min_time_step must not exceed max_time_step.")
        return self


class SimulationConfig(EngineConfig):
    environment: EnvironmentConfig
    motor: MotorConfig | None
    rocket: RocketConfig
    flight: FlightConfig
    surfaces: list[SurfaceConfig] = Field(default_factory=list)
    tanks: list[MassBasedTankConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def compatible_tanks(self):
        needs_tanks = isinstance(self.motor, (LiquidMotorConfig, HybridMotorConfig))
        if needs_tanks and not self.tanks:
            raise ValueError("Liquid and hybrid motors require configured tanks.")
        if not needs_tanks and self.tanks:
            raise ValueError("Tanks are supported only for liquid and hybrid motors.")
        return self


TELEMETRY_COLUMNS = (
    "time_s",
    "x_m",
    "y_m",
    "z_asl_m",
    "vx_m_s",
    "vy_m_s",
    "vz_m_s",
    "e0",
    "e1",
    "e2",
    "e3",
    "w1_rad_s",
    "w2_rad_s",
    "w3_rad_s",
)


class TelemetryQuery(EngineConfig):
    columns: Annotated[list[str], Field(min_length=1, max_length=14)] = Field(
        default_factory=lambda: ["time_s", "x_m", "y_m", "z_asl_m"]
    )
    start_time: Number | None = None
    end_time: Number | None = None
    max_points: Annotated[int, Field(ge=32, le=10_000)] = 2000

    @field_validator("columns")
    @classmethod
    def known_columns(cls, value):
        if len(set(value)) != len(value) or any(
            v not in TELEMETRY_COLUMNS for v in value
        ):
            raise ValueError("Telemetry columns must be unique known column names.")
        return value

    @model_validator(mode="after")
    def ordered_interval(self):
        if (
            self.start_time is not None
            and self.end_time is not None
            and self.start_time > self.end_time
        ):
            raise ValueError("start_time must not exceed end_time.")
        return self


RunState = Literal[
    "queued",
    "running",
    "cancelling",
    "succeeded",
    "failed",
    "cancelled",
    "timed_out",
    "interrupted",
]


class RunRecord(EngineConfig):
    run_id: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
    state: RunState
    stage: str
    created_at: str
    started_at: str | None
    finished_at: str | None
    worker_pid: Annotated[int, Field(gt=0)] | None
    peak_rss_bytes: Annotated[int, Field(ge=0)]
    error: str | None


class ParachuteEvent(EngineConfig):
    name: str
    trigger_time_s: Number


class FlightSummary(EngineConfig):
    name: str
    initial_mass_kg: Positive
    final_mass_kg: Positive
    initial_center_of_mass_m: Number
    final_center_of_mass_m: Number
    termination_reason: Literal["impact", "apogee", "time_limit", "stopped"]
    apogee_reached: bool
    landed: bool
    start_time_s: Number
    end_time_s: Number
    duration_s: NonNegative
    apogee_asl_m: Number | None
    apogee_agl_m: Number | None
    apogee_time_s: Number | None
    max_altitude_asl_m: Number
    max_altitude_agl_m: Number
    max_speed_m_s: NonNegative
    max_speed_time_s: Number
    impact_x_m: Number | None
    impact_y_m: Number | None
    impact_speed_m_s: NonNegative | None
    ground_model: Literal["flat", "terrain"] = "flat"
    impact_latitude: Number | None = None
    impact_longitude: Number | None = None
    impact_elevation_m: Number | None = None
    parachute_events: list[ParachuteEvent]


class TelemetryResult(EngineConfig):
    columns: list[str]
    data: list[list[Number]]
    total_rows: Annotated[int, Field(ge=0)]
    matched_rows: Annotated[int, Field(ge=0)]
    returned_rows: Annotated[int, Field(ge=0)]
    decimated: bool

    @model_validator(mode="after")
    def consistent_rows(self):
        if not self.returned_rows <= self.matched_rows <= self.total_rows:
            raise ValueError("Invalid telemetry row counts.")
        if len(self.data) != self.returned_rows or any(
            len(row) != len(self.columns) for row in self.data
        ):
            raise ValueError("Telemetry rows must match the declared dimensions.")
        return self
