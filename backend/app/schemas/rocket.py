"""Rocket runtime inputs, aerodynamic surfaces, and recovery hardware."""

from math import isclose
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from .aerodynamics import DragGeometry
from .common import (
    EngineConfig,
    Inertia,
    NonNegative,
    NonNegativeCurve,
    Number,
    Positive,
    _inertia,
)


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
    coordinate_system_orientation: Literal["tail_to_nose", "nose_to_tail"] = (
        "tail_to_nose"
    )
    parachutes: list[ParachuteConfig] = Field(default_factory=list)
    rail_buttons: RailButtonsConfig | None = None
    automatic_drag: DragGeometry | None = None

    @model_validator(mode="after")
    def drag_reference(self):
        if self.automatic_drag is not None and not isclose(
            self.automatic_drag.reference_radius_m, self.radius, rel_tol=1e-7
        ):
            raise ValueError(
                "Automatic drag reference radius must match rocket radius."
            )
        return self

    @field_validator("inertia")
    @classmethod
    def body_tensor(cls, value):
        return _inertia(value)


Position = Number | tuple[Number, Number, Number]


class SurfaceBase(EngineConfig):
    position: Position
    rocket_radius: Positive


class NoseConeConfig(SurfaceBase):
    surface_type: Literal["nose"] = "nose"
    length: Positive
    kind: Literal[
        "conical",
        "ogive",
        "elliptical",
        "parabolic",
        "lvhaack",
        "vonkarman",
        "powerseries",
        "haack",
    ] = "conical"
    base_radius: Positive | None = None
    bluffness: Annotated[Number, Field(ge=0, lt=1)] | None = None
    power: Annotated[Number, Field(gt=0, le=1)] | None = None
    haack_c: Annotated[Number, Field(ge=0, le=1 / 3)] | None = None

    @model_validator(mode="after")
    def compatible_power_series(self):
        if self.kind == "haack":
            if self.haack_c is None:
                raise ValueError("A Haack nose cone requires haack_c.")
            if self.bluffness not in (None, 0):
                raise ValueError(
                    "Continuous Haack profiles currently require a sharp tip."
                )
        elif self.haack_c is not None:
            raise ValueError("haack_c is only used with kind='haack'.")
        if self.kind == "powerseries":
            if self.power is None:
                raise ValueError("A power-series nose cone requires power.")
            if self.bluffness not in (None, 0):
                raise ValueError("A power-series nose cone cannot use bluffness.")
        return self


class TrapezoidalFinsConfig(SurfaceBase):
    surface_type: Literal["trapezoidal_fins"] = "trapezoidal_fins"
    n: Annotated[int, Field(ge=3)]
    root_chord: Positive
    tip_chord: NonNegative
    span: Positive
    cant_angle: Number = 0.0
    sweep_length: Number | None = None
    sweep_angle: Annotated[Number, Field(gt=-90, lt=90)] | None = None

    @model_validator(mode="after")
    def one_sweep_definition(self):
        if self.sweep_length is not None and self.sweep_angle is not None:
            raise ValueError("Specify sweep_length or sweep_angle, not both.")
        return self


class EllipticalFinsConfig(SurfaceBase):
    surface_type: Literal["elliptical_fins"] = "elliptical_fins"
    n: Annotated[int, Field(ge=3)]
    root_chord: Positive
    span: Positive
    cant_angle: Number = 0.0


class TailConfig(SurfaceBase):
    surface_type: Literal["tail"] = "tail"
    top_radius: Positive
    bottom_radius: Positive
    length: Positive


SurfaceConfig = Annotated[
    NoseConeConfig | TrapezoidalFinsConfig | EllipticalFinsConfig | TailConfig,
    Field(discriminator="surface_type"),
]
