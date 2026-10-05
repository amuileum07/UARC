"""Serializable simulation inputs; RocketPy runtime objects belong in the engine."""

from datetime import datetime
from math import isclose
from typing import Annotated, Literal

import numpy as np
from pydantic import (
    AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator,
)

Number = Annotated[float, Field(strict=True, allow_inf_nan=False)]
Positive = Annotated[Number, Field(gt=0)]
NonNegative = Annotated[Number, Field(ge=0)]


def _ordered_curve(value):
    if isinstance(value, list) and any(
        left[0] >= right[0] for left, right in zip(value, value[1:])
    ):
        raise ValueError("Curve coordinates must be strictly increasing.")
    return value


# Paths are data, but resolving/authorizing them belongs to the application.
Curve = Annotated[
    Number | str | Annotated[list[tuple[Number, Number]], Field(min_length=2)],
    AfterValidator(_ordered_curve),
]
PositiveCurve = Annotated[
    Positive | str | Annotated[list[tuple[Number, Positive]], Field(min_length=2)],
    AfterValidator(_ordered_curve),
]
NonNegativeCurve = Annotated[
    NonNegative | str | Annotated[list[tuple[Number, NonNegative]], Field(min_length=2)],
    AfterValidator(_ordered_curve),
]
Inertia = (
    tuple[Number, Number, Number]
    | tuple[Number, Number, Number, Number, Number, Number]
)
BurnTime = Positive | tuple[NonNegative, Number] | None
Tolerance = Positive | Annotated[tuple[Positive, ...], Field(min_length=13, max_length=13)]


def _inertia(value: Inertia, *, allow_zero=False):
    # RocketPy checks component count, not physical principal moments.
    i11, i22, i33, i12, i13, i23 = value if len(value) == 6 else (*value, 0, 0, 0)
    principal = np.linalg.eigvalsh([[i11, i12, i13], [i12, i22, i23], [i13, i23, i33]])
    if principal[0] < 0 or (not allow_zero and principal[0] == 0):
        raise ValueError("Inertia needs positive principal moments (nonnegative for a motor).")
    if principal[2] > principal[0] + principal[1] + 1e-12 * max(1, principal[2]):
        raise ValueError("Inertia principal moments must satisfy the triangle inequality.")
    return value


class EngineConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class EnvironmentConfig(EngineConfig):
    latitude: Annotated[Number, Field(ge=-90, le=90)]
    longitude: Annotated[Number, Field(ge=-180, le=180)]
    elevation: Number
    date: datetime | tuple[int, int, int, int] | None = None
    timezone: str = "UTC"
    gravity: Positive | None = None
    datum: Literal["SIRGAS2000", "WGS84", "NAD83", "SAD69"] = "SIRGAS2000"
    max_expected_height: Number = 80000.0
    pressure: PositiveCurve | None = None
    temperature: PositiveCurve | None = None
    wind_u: Curve = 0.0
    wind_v: Curve = 0.0
    atmosphere_type: Literal[
        "standard_atmosphere", "custom_atmosphere", "forecast", "reanalysis",
        "ensemble", "windy", "wyoming_sounding",
    ] | None = None
    atmosphere_file: str | None = None
    atmosphere_dictionary: dict[str, str | None] | str | None = None
    pressure_conversion_factor: Literal["Pa", "hPa", "mbar"] | Positive | None = None
    ensemble_member: Annotated[int, Field(ge=0)] = 0

    @field_validator("atmosphere_type", mode="before")
    @classmethod
    def normalize_model(cls, value):
        return value.lower() if isinstance(value, str) else value

    @field_validator("date")
    @classmethod
    def valid_date(cls, value):
        if isinstance(value, tuple):
            datetime(*value)
        return value

    @model_validator(mode="after")
    def compatible_weather(self):
        if self.max_expected_height <= self.elevation:
            raise ValueError("max_expected_height must be above the launch elevation.")
        custom = (
            self.pressure is not None or self.temperature is not None
            or self.wind_u != 0 or self.wind_v != 0
        )
        self.atmosphere_type = self.atmosphere_type or (
            "custom_atmosphere" if custom else "standard_atmosphere"
        )
        if self.atmosphere_type != "custom_atmosphere" and custom:
            raise ValueError("Weather overrides require custom_atmosphere.")
        local = self.atmosphere_type in {"standard_atmosphere", "custom_atmosphere"}
        if local and any(v is not None for v in (
            self.atmosphere_file, self.atmosphere_dictionary, self.pressure_conversion_factor,
        )):
            raise ValueError("Local atmospheres do not use an external weather source.")
        if not local and self.atmosphere_file is None:
            raise ValueError("An external atmosphere requires atmosphere_file.")
        if self.atmosphere_type in {"forecast", "reanalysis", "ensemble", "windy"} and self.date is None:
            raise ValueError("This atmosphere model requires a launch date.")
        if self.atmosphere_type != "ensemble" and self.ensemble_member != 0:
            raise ValueError("ensemble_member is only used with an ensemble atmosphere.")
        return self


class MotorBase(EngineConfig):
    """Common motor fields; concrete models declare their required inputs."""

    thrust_source: NonNegativeCurve
    nozzle_radius: Positive
    dry_mass: NonNegative | None
    dry_inertia: Inertia
    burn_time: BurnTime = None
    nozzle_position: Number = 0.0
    reshape_thrust_curve: Literal[False] | tuple[Positive, Positive] = False
    interpolation_method: Literal["linear", "akima", "spline"] = "linear"
    coordinate_system_orientation: Literal[
        "nozzle_to_combustion_chamber", "combustion_chamber_to_nozzle"
    ] = "nozzle_to_combustion_chamber"
    reference_pressure: Positive | None = None

    @field_validator("dry_inertia")
    @classmethod
    def dry_tensor(cls, value):
        return _inertia(value, allow_zero=True)

    @field_validator("burn_time")
    @classmethod
    def positive_duration(cls, value):
        if isinstance(value, tuple) and value[1] <= value[0]:
            raise ValueError("burn_time must describe a positive duration.")
        return value


class GrainMotorBase(MotorBase):
    center_of_dry_mass_position: Number
    grain_number: Annotated[int, Field(gt=0)]
    grain_density: Positive
    grain_outer_radius: Positive
    grain_initial_inner_radius: NonNegative
    grain_initial_height: Positive
    grain_separation: NonNegative
    grains_center_of_mass_position: Number
    throat_radius: Positive = 0.01
    only_radial_burn: bool = False

    @model_validator(mode="after")
    def grain_geometry(self):
        if self.grain_initial_inner_radius >= self.grain_outer_radius:
            raise ValueError("The grain inner radius must be smaller than its outer radius.")
        return self


class SolidMotorConfig(GrainMotorBase):
    motor_type: Literal["solid"] = "solid"


class LiquidMotorConfig(MotorBase):
    motor_type: Literal["liquid"] = "liquid"
    center_of_dry_mass_position: Number


class HybridMotorConfig(GrainMotorBase):
    motor_type: Literal["hybrid"] = "hybrid"
    only_radial_burn: bool = True


class GenericMotorConfig(MotorBase):
    motor_type: Literal["generic"] = "generic"
    burn_time: BurnTime
    chamber_radius: Positive
    chamber_height: Positive
    chamber_position: Number
    propellant_initial_mass: NonNegative
    dry_mass: NonNegative | None = 0.0
    dry_inertia: Inertia = (0, 0, 0)
    center_of_dry_mass_position: Number | None = None


MotorConfig = Annotated[
    SolidMotorConfig | LiquidMotorConfig | HybridMotorConfig | GenericMotorConfig,
    Field(discriminator="motor_type"),
]


class ParachuteConfig(EngineConfig):
    name: str
    cd_s: Positive
    trigger: Literal["apogee"] | NonNegative
    sampling_rate: Positive = 100.0
    lag: NonNegative = 0.0
    noise: tuple[Number, NonNegative, Annotated[Number, Field(ge=-1, le=1)]] = (0, 0, 0)
    radius: Positive | None = None
    height: Positive | None = None
    porosity: Annotated[Number, Field(ge=0, le=1)] = 0.0432
    drag_coefficient: Positive = 1.4


class RailButtonsConfig(EngineConfig):
    upper_button_position: Number
    lower_button_position: Number
    angular_position: Number = 45.0
    radius: Positive | None = None


class RocketConfig(EngineConfig):
    radius: Positive
    mass: Positive
    inertia: Inertia
    power_off_drag: NonNegativeCurve
    power_on_drag: NonNegativeCurve
    center_of_mass_without_motor: Number
    motor_position: Number = 0.0
    coordinate_system_orientation: Literal["tail_to_nose", "nose_to_tail"] = "tail_to_nose"
    parachutes: list[ParachuteConfig] = Field(default_factory=list)
    rail_buttons: RailButtonsConfig | None = None

    @field_validator("inertia")
    @classmethod
    def body_tensor(cls, value):
        return _inertia(value)


class FlightConfig(EngineConfig):
    rail_length: Positive
    inclination: Number
    heading: Number
    initial_solution: Annotated[tuple[Number, ...], Field(min_length=14, max_length=14)] | None = None
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
