"""Validated Python inputs for the engine; native RocketPy objects stay in Python."""

from collections.abc import Callable
from datetime import datetime
from inspect import signature
from numbers import Real
from os import PathLike
from typing import Annotated, Any, Literal, cast

import numpy as np
from pydantic import (
    BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator,
)
from rocketpy import (
    AeroSurface, Flight, GenericMotor, HybridMotor, LiquidMotor, SolidMotor, Tank,
)

Number = Annotated[float, Field(strict=True, allow_inf_nan=False)]
Positive = Annotated[Number, Field(gt=0)]
NonNegative = Annotated[Number, Field(ge=0)]
_number = TypeAdapter(Number)
MOTOR_TYPES = {
    "solid": SolidMotor, "liquid": LiquidMotor,
    "hybrid": HybridMotor, "generic": GenericMotor,
}


def _curve(value: Any, *, positive=False, nonnegative=False) -> Any:
    """Check in-memory data; leave actual file loading/function evaluation to RocketPy."""
    if isinstance(value, (str, PathLike)):
        return str(value)
    if callable(value):
        return value
    if isinstance(value, Real):
        result = _number.validate_python(value)
        data = np.asarray([result])
    else:
        result = np.asarray(value, dtype=float)
        if (
            result.ndim != 2 or result.shape[1] != 2 or len(result) < 2
            or not np.isfinite(result).all() or np.any(np.diff(result[:, 0]) <= 0)
        ):
            raise ValueError("A curve needs finite (x, value) pairs with increasing x.")
        data = result[:, 1]
    if (positive and np.any(data <= 0)) or (nonnegative and np.any(data < 0)):
        raise ValueError("Curve values must be positive/nonnegative as required.")
    return result


def _inertia(value, *, allow_zero=False):
    if len(value) not in (3, 6):
        raise ValueError("Inertia must contain 3 or 6 components in kg*m^2.")
    i11, i22, i33, i12, i13, i23 = value if len(value) == 6 else (*value, 0, 0, 0)
    principal = np.linalg.eigvalsh([[i11, i12, i13], [i12, i22, i23], [i13, i23, i33]])
    if principal[0] < 0 or (not allow_zero and principal[0] == 0):
        raise ValueError("Inertia needs positive principal moments (nonnegative for a motor).")
    if principal[2] > principal[0] + principal[1] + 1e-12 * max(1, principal[2]):
        raise ValueError("Inertia principal moments must satisfy the triangle inequality.")
    return value


class EngineConfig(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid", strict=True)


class EnvironmentConfig(EngineConfig):
    latitude: Annotated[Number, Field(ge=-90, le=90)]
    longitude: Annotated[Number, Field(ge=-180, le=180)]
    elevation: Number
    date: datetime | tuple[int, int, int, int] | None = None
    timezone: str = "UTC"
    gravity: Positive | None = None
    datum: Literal["SIRGAS2000", "WGS84", "NAD83", "SAD69"] = "SIRGAS2000"
    max_expected_height: Number = 80000.0
    # RocketPy profiles accept scalar/table/file/callable/Function inputs.
    pressure: Any = None
    temperature: Any = None
    wind_u: Any = 0.0
    wind_v: Any = 0.0
    atmosphere_type: Literal[
        "standard_atmosphere", "custom_atmosphere", "forecast", "reanalysis",
        "ensemble", "windy", "wyoming_sounding",
    ] | None = None
    atmosphere_file: Any = None
    atmosphere_dictionary: dict[str, Any] | str | None = None
    pressure_conversion_factor: Literal["Pa", "hPa", "mbar"] | Positive | None = None
    ensemble_member: Annotated[int, Field(ge=0)] = 0

    @field_validator("atmosphere_type", mode="before")
    @classmethod
    def normalize_model(cls, value):
        return value.lower() if isinstance(value, str) else value

    @field_validator("pressure", "temperature")
    @classmethod
    def positive_profile(cls, value):
        return None if value is None else _curve(value, positive=True)

    @field_validator("wind_u", "wind_v")
    @classmethod
    def wind_profile(cls, value):
        return _curve(value)

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
        custom = self.pressure is not None or self.temperature is not None or any(
            not isinstance(wind, Real) or wind != 0 for wind in (self.wind_u, self.wind_v)
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


class MotorParameters(EngineConfig):
    """Native keyword fields; required fields depend on the selected motor class."""

    thrust_source: Any
    dry_mass: NonNegative | None = None
    dry_inertia: tuple[Number, ...] | None = None
    nozzle_radius: Positive | None = None
    grain_number: Annotated[int, Field(gt=0)] | None = None
    grain_density: Positive | None = None
    grain_outer_radius: Positive | None = None
    grain_initial_inner_radius: NonNegative | None = None
    grain_initial_height: Positive | None = None
    grain_separation: NonNegative | None = None
    grains_center_of_mass_position: Number | None = None
    center_of_dry_mass_position: Number | None = None
    nozzle_position: Number = 0.0
    burn_time: Positive | tuple[NonNegative, Number] | None = None
    throat_radius: Positive | None = None
    reshape_thrust_curve: Literal[False] | tuple[Positive, Positive] = False
    interpolation_method: Literal["linear", "akima", "spline"] = "linear"
    coordinate_system_orientation: Literal[
        "nozzle_to_combustion_chamber", "combustion_chamber_to_nozzle"
    ] = "nozzle_to_combustion_chamber"
    reference_pressure: Positive | None = None
    only_radial_burn: bool = False
    chamber_radius: Positive | None = None
    chamber_height: Positive | None = None
    chamber_position: Number | None = None
    propellant_initial_mass: NonNegative | None = None

    @field_validator("thrust_source")
    @classmethod
    def thrust_curve(cls, value):
        return _curve(value, nonnegative=True)

    @field_validator("dry_inertia")
    @classmethod
    def dry_tensor(cls, value):
        return None if value is None else _inertia(value, allow_zero=True)

    @model_validator(mode="after")
    def consistent_motor(self):
        if isinstance(self.burn_time, tuple) and self.burn_time[1] <= self.burn_time[0]:
            raise ValueError("burn_time must describe a positive duration.")
        if self.grain_initial_inner_radius is not None and self.grain_outer_radius is not None:
            if self.grain_initial_inner_radius >= self.grain_outer_radius:
                raise ValueError("The grain inner radius must be smaller than its outer radius.")
        return self


class MotorConfig(EngineConfig):
    motor_type: Literal["solid", "liquid", "hybrid", "generic"] = "solid"
    parameters: MotorParameters
    tanks: list[tuple[Tank, Number]] = Field(default_factory=list)

    @model_validator(mode="after")
    def compatible_motor(self):
        liquid = self.motor_type in {"liquid", "hybrid"}
        if liquid and not self.tanks:
            raise ValueError("Liquid and hybrid motors require configured tanks.")
        if not liquid and self.tanks:
            raise ValueError("Tanks are supported only for liquid and hybrid motors.")
        parameters = self.parameters.model_dump(exclude_unset=True)
        nullable = {"dry_mass", "burn_time", "reference_pressure"}
        if self.motor_type == "generic":
            nullable.add("center_of_dry_mass_position")
        for name, value in parameters.items():
            if value is None and name not in nullable:
                raise ValueError(f"{name} cannot be None for a {self.motor_type} motor.")
        try:
            signature(MOTOR_TYPES[self.motor_type]).bind(**parameters)
        except TypeError as error:
            raise ValueError(str(error)) from error
        return self


class ParachuteConfig(EngineConfig):
    name: str
    cd_s: Positive
    trigger: Literal["apogee"] | NonNegative | Callable[..., bool]
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
    inertia: tuple[Number, ...]
    power_off_drag: Any
    power_on_drag: Any
    center_of_mass_without_motor: Number
    motor_position: Number = 0.0
    coordinate_system_orientation: Literal["tail_to_nose", "nose_to_tail"] = "tail_to_nose"
    surfaces: list[tuple[AeroSurface, Number | tuple[Number, Number, Number]]] = Field(default_factory=list)
    parachutes: list[ParachuteConfig] = Field(default_factory=list)
    rail_buttons: RailButtonsConfig | None = None

    @field_validator("inertia")
    @classmethod
    def body_tensor(cls, value):
        return _inertia(value)

    @field_validator("power_off_drag", "power_on_drag")
    @classmethod
    def drag_curve(cls, value):
        return _curve(value, nonnegative=True)


class FlightConfig(EngineConfig):
    rail_length: Positive
    inclination: Number
    heading: Number
    initial_solution: Flight | tuple[Number, ...] | None = None
    terminate_on_apogee: bool = False
    max_time: Positive = 600.0
    max_time_step: Annotated[float, Field(gt=0)] = float("inf")
    min_time_step: NonNegative = 0.0
    rtol: Positive | tuple[Positive, ...] = 1e-6
    atol: Positive | tuple[Positive, ...] | None = None
    time_overshoot: bool = True
    verbose: bool = False
    name: str = "Flight"
    equations_of_motion: Literal["standard", "solid_propulsion"] = "standard"
    ode_solver: Any = "LSODA"
    simulation_mode: Literal["6 DOF", "3 DOF"] = "6 DOF"

    @field_validator("initial_solution", mode="before")
    @classmethod
    def initial_state(cls, value):
        if isinstance(value, Flight):
            return tuple(value.solution[-1])
        if isinstance(value, (list, np.ndarray)):
            return tuple(value)
        return value

    @field_validator("rtol", "atol", mode="before")
    @classmethod
    def tolerance_array(cls, value):
        return tuple(value) if isinstance(value, (list, np.ndarray)) else value

    @model_validator(mode="after")
    def consistent_flight(self):
        self.heading %= 360
        start = 0.0
        if self.initial_solution is None:
            if not 0 < self.inclination <= 90:
                raise ValueError("Rail launch inclination must be in (0, 90] degrees.")
        else:
            # The before validator converts a Flight into its final state tuple.
            state = cast(tuple[float, ...], self.initial_solution)
            if len(state) != 14 or not np.isclose(np.linalg.norm(state[7:11]), 1, rtol=0, atol=1e-6):
                raise ValueError("initial_solution needs 14 values and a unit attitude quaternion.")
            start = state[0]
        if self.max_time <= start:
            raise ValueError("max_time must be later than the initial simulation time.")
        if self.min_time_step > self.max_time_step:
            raise ValueError("min_time_step must not exceed max_time_step.")
        for value in (self.rtol, self.atol):
            if isinstance(value, tuple) and len(value) != 13:
                raise ValueError("A tolerance array must contain 13 values.")
        return self
