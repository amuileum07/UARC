"""Serializable inputs and diagnostics for independent preliminary Cd0 models."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .common import EngineConfig, NonNegative, Number, Positive


class AutomaticDrag(EngineConfig):
    model: Literal["subsonic_v1", "compressible_v1"] = "subsonic_v1"


class DragFin(EngineConfig):
    """Sharp symmetric double wedge, maximum thickness at half chord, SI units."""

    count: Annotated[int, Field(ge=3, le=4)]
    root_chord_m: Positive
    tip_chord_m: Positive
    span_m: Positive
    thickness_m: Positive
    midchord_sweep_deg: Annotated[Number, Field(ge=-10, le=10)]

    @model_validator(mode="after")
    def thin_section(self):
        if self.thickness_m / min(self.root_chord_m, self.tip_chord_m) > 0.05:
            raise ValueError(
                "Compressible Cd0 requires fin thickness/chord ≤ 0.05 everywhere."
            )
        area = (self.root_chord_m + self.tip_chord_m) * self.span_m / 2
        parameter = (
            self.span_m**2 / area * (self.thickness_m / self.root_chord_m) ** (1 / 3)
        )
        # Eq. 4-35's fitted sonic coefficient becomes negative below this value;
        # reject the fit's nonphysical tail rather than silently clipping drag.
        if parameter <= 0.0308 / 6.08:
            raise ValueError(
                "Fin aspect ratio is outside the positive sonic-thickness correlation; use a measured drag curve."
            )
        return self


class SupersonicPressure(EngineConfig):
    mach: Annotated[Number, Field(ge=1.2, le=3)]
    nose: NonNegative
    fins: NonNegative


class CompressibleGeometry(EngineConfig):
    nose_length_m: Positive
    fins: Annotated[list[DragFin], Field(max_length=63)]
    pressure: Annotated[list[SupersonicPressure], Field(min_length=2, max_length=128)]

    @model_validator(mode="after")
    def ordered_pressure(self):
        machs = [row.mach for row in self.pressure]
        if (
            machs[0] != 1.2
            or machs[-1] != 3
            or any(b <= a for a, b in zip(machs, machs[1:], strict=False))
        ):
            raise ValueError(
                "Supersonic pressure samples must increase from Mach 1.2 to 3."
            )
        return self


class DragSurface(EngineConfig):
    component_id: str
    kind: Literal["body", "fin"]
    length_m: Positive
    wetted_area_m2: Positive
    form_factor: Annotated[Number, Field(ge=1)]
    roughness_m: NonNegative = 0.0

    @model_validator(mode="after")
    def small_roughness(self):
        if self.roughness_m >= self.length_m / 100:
            raise ValueError("Equivalent sand-grain roughness must be below L/100.")
        return self


class DragGeometry(EngineConfig):
    model: Literal["subsonic_v1", "compressible_v1"] = "subsonic_v1"
    reference_radius_m: Positive
    body_length_m: Positive
    nozzle_radius_m: NonNegative = 0.0
    surfaces: Annotated[list[DragSurface], Field(min_length=1, max_length=64)]
    compressible: CompressibleGeometry | None = None

    @model_validator(mode="after")
    def valid_base(self):
        if self.nozzle_radius_m >= self.reference_radius_m:
            raise ValueError("The nozzle exit must be smaller than the body base.")
        if not any(surface.kind == "body" for surface in self.surfaces):
            raise ValueError("Automatic drag requires a body surface.")
        if (self.model == "compressible_v1") != (self.compressible is not None):
            raise ValueError(
                "Compressible geometry is required only for compressible_v1."
            )
        if self.compressible is not None:
            fineness = self.compressible.nose_length_m / (2 * self.reference_radius_m)
            if (
                not 3 - 1e-9 <= fineness <= 10 + 1e-9
                or self.compressible.nose_length_m >= self.body_length_m
            ):
                raise ValueError(
                    "Compressible Cd0 needs conical nose length/diameter 3–10 and a tube."
                )
        return self


class DragSample(EngineConfig):
    mach: NonNegative
    reynolds_diameter: NonNegative
    skin_friction: NonNegative
    form: NonNegative
    base_off: NonNegative
    base_on: NonNegative
    total_off: NonNegative
    total_on: NonNegative
    nose_pressure: NonNegative = 0.0
    fin_pressure: NonNegative = 0.0


class DragReport(EngineConfig):
    model: Literal["subsonic_v1", "compressible_v1"] = "subsonic_v1"
    reference_area_m2: Positive
    reference_temperature_k: Positive
    reference_pressure_pa: Positive
    max_mach: Positive
    samples: list[DragSample]
    notes: list[str]
