"""Motor variants, fluids, and propellant tanks."""

from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from .common import (
    BurnTime,
    EngineConfig,
    Inertia,
    NonNegative,
    NonNegativeCurve,
    Number,
    Positive,
    _inertia,
)


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
            raise ValueError(
                "The grain inner radius must be smaller than its outer radius."
            )
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


class FluidConfig(EngineConfig):
    name: str
    density: Positive


class MassBasedTankConfig(EngineConfig):
    """A cylindrical tank with caller-supplied phase masses, in SI units."""

    name: str
    position: Number
    radius: Positive
    height: Positive
    spherical_caps: bool = False
    flux_time: Positive | tuple[NonNegative, Number]
    liquid: FluidConfig
    gas: FluidConfig
    liquid_mass: NonNegativeCurve
    gas_mass: NonNegativeCurve
    discretize: Annotated[int, Field(ge=2, le=100_000)] = 100

    @field_validator("flux_time")
    @classmethod
    def positive_duration(cls, value):
        if isinstance(value, tuple) and value[1] <= value[0]:
            raise ValueError("flux_time must describe a positive duration.")
        return value
